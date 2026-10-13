from asyncio import Queue, QueueFull, QueueShutDown, Task, current_task, gather
from collections.abc import Awaitable, Callable, Iterator
from typing import NamedTuple

from .exceptions import ChannelClosed, DomainError, SenderOverflow
from .logger import get_logger
from .model import BaseRequest, DataModel, Pipeline, Sender

log = get_logger(__name__)


class Channel[T]:
    """한 프로세스 안에서 데이터를 넘기는 큐. 호출하면 `send()`라 그대로 `Sender`로 쓸 수 있다.

    `maxsize`가 0이면 크기 제한이 없다.
    """

    def __init__(self, maxsize: int = 0):
        self._q = Queue[T](maxsize)

    async def send(self, data: T) -> None:
        try:
            return await self._q.put(data)
        except QueueShutDown as exc:
            raise ChannelClosed("'Channel'이 이미 닫혔다. - send()") from exc

    def try_send(self, data: T) -> bool:
        """기다리지 않고 넣는다. 가득 차 넣지 못했으면 `False`를 돌려준다."""

        try:
            self._q.put_nowait(data)
        except QueueFull:
            return False
        except QueueShutDown as exc:
            raise ChannelClosed("'Channel'이 이미 닫혔다. - try_send()") from exc
        return True

    async def __call__(self, data: T) -> None:
        return await self.send(data)

    async def recv(self) -> T:
        try:
            return await self._q.get()
        except QueueShutDown as exc:
            raise ChannelClosed("'Channel'이 이미 닫혔다. - recv()") from exc

    def shutdown(self):
        self._q.shutdown()


class PipelineSender:
    """상위 데이터를 그 데이터를 처리할 파이프라인과 함께 슬롯 채널로 보낸다.

    슬롯 채널에 넣기만 하고 기다리지 않는다. 슬롯이 밀려 채널이 가득 차면 데이터를 버리고
    `on_overflow`를 부른다. 기다리면 공유된 상위 generator와 그 다른 소비자가 함께 멈춘다.
    """

    def __init__(
        self,
        channel: Channel[tuple[DataModel, Pipeline]],
        pipeline: Pipeline,
        on_overflow: Callable[[], Awaitable[None]] | None = None,
    ):
        self._channel = channel
        self._pipeline = pipeline
        self._on_overflow = on_overflow

    @property
    def pipeline(self):
        return self._pipeline

    async def __call__(self, data: DataModel):
        try:
            if not self._channel.try_send((data, self._pipeline)) and self._on_overflow:
                await self._on_overflow()
        except ChannelClosed:
            # 슬롯은 상위 구독이 갱신되기 전에 닫힌다. 그 사이 온 데이터는 받을 소비자가
            # 없으므로 버린다. 예외로 올리면 `SymbolRouter`를 거쳐 공유된 상위 generator가
            # 죽고, 다른 소비자가 같은 상위 심볼을 계속 구독 중이면 재시작되지도 않는다.
            pass


class SenderOutbox:
    """소비자 `Sender` 앞에 두는 크기 제한 큐. 넣기만 하고 곧바로 돌아온다.

    라우터는 데이터 하나를 그 심볼의 Sender 모두에게 보낸 뒤에야 다음 데이터로 간다. 그래서
    Sender 하나가 느리면 공유 generator와 다른 소비자가 함께 늦어진다. outbox는 데이터를 큐에 넣고
    돌아오고, 실제 전송은 `run()` 태스크가 따로 한다.

    큐가 가득 차거나(`SenderOverflow`) 전송이 던지면 outbox는 실패한 채로 남는다. 그 뒤 호출은 그
    예외를 던지므로 라우터가 이 Sender를 떼어 내고 실패를 알린다. 전송이 던졌을 때는 다음 데이터를
    기다리지 않도록 `on_failed`도 부른다. 막힌 소비자를 얼마나 기다릴지는 Sender가 스스로 정한다
    (타임아웃이 지나면 던진다). 정하지 않아도 큐가 차면 떨어져 나간다.
    """

    def __init__(
        self,
        sender: Sender[DataModel],
        max_pending: int,
        on_failed: Callable[[Exception], Awaitable[None]] | None = None,
    ):
        self._sender = sender
        self._q = Queue[DataModel](max_pending)
        self._on_failed = on_failed
        self._failed: Exception | None = None
        self._task: Task[None] | None = None

    @property
    def failed(self) -> Exception | None:
        """outbox를 실패시킨 예외. 실패하지 않았으면 `None`."""

        return self._failed

    async def __call__(self, data: DataModel) -> None:
        failed = self._failed
        if failed is None:
            try:
                self._q.put_nowait(data)
                return
            except QueueFull:
                failed = SenderOverflow(f"보내지 못한 데이터가 {self._q.maxsize}건 쌓였다.")
                self._fail(failed)
        raise failed

    async def run(self) -> None:
        """큐의 데이터를 Sender로 보낸다. 태스크로 띄운다."""

        self._task = current_task()
        while self._failed is None:
            try:
                data = await self._q.get()
            except QueueShutDown:
                return
            try:
                await self._sender(data)
            except Exception as exc:
                self._fail(exc)
                if self._on_failed is not None:
                    await self._on_failed(exc)

    def close(self) -> None:
        """쌓인 데이터를 버리고 전달 태스크를 끝낸다. 막힌 전송은 취소한다. 기다리지 않는다."""

        self._q.shutdown(immediate=True)
        if self._task is not None and self._task is not current_task():
            self._task.cancel()

    def _fail(self, exc: Exception) -> None:
        """실패로 표시하고 닫는다."""

        if self._failed is not None:
            return
        self._failed = exc
        self.close()


type OnFail = Callable[[set[str], Exception], Awaitable[None]]
"""구독이 실패했을 때 그 센더의 심볼과 원인을 받는 콜백.

라우터는 이 콜백을 데이터를 보내던 태스크 안에서 부른다. 스테이지 락을 잡으면 하위
`update()`(하위 락 → 상위 락)와 교착할 수 있으므로, 콜백은 할 일을 태스크로 띄우고 곧바로
돌아와야 한다.
"""


class SymbolRouter:
    """(Sender, 심볼) 구독을 모아 데이터를 `data.symbol`을 구독한 Sender에게만 보낸다."""

    def __init__(self):
        self._senders_by_symbol: dict[str, set[Sender[DataModel]]] = {}
        self._on_fail: dict[Sender[DataModel], OnFail] = {}

    def add(self, sender: Sender[DataModel], symbol: str):
        if not symbol:
            raise DomainError("`symbol`은 한문자라도 있어야 한다.")
        senders = self._senders_by_symbol.setdefault(symbol, set())
        senders.add(sender)

    def remove(self, sender: Sender[DataModel], symbol: str = ""):
        """`sender`의 `symbol` 구독을 뺀다. `symbol`이 없으면 실패 콜백까지 모두 뺀다."""

        if symbol:
            if senders := self._senders_by_symbol.get(symbol):
                senders.discard(sender)
        else:
            for senders in self._senders_by_symbol.values():
                senders.discard(sender)
            self._on_fail.pop(sender, None)

    def replace(self, sender: Sender[DataModel], symbols: set[str], on_fail: OnFail | None = None):
        """`sender`의 구독 심볼을 `symbols`로 바꾼다. 빈 집합이면 구독이 사라진다.

        `on_fail`은 이 센더의 구독이 실패했을 때 부른다(`__call__()`·`drain()`).
        """

        self.remove(sender)
        for symbol in symbols:
            self.add(sender, symbol)
        if symbols and on_fail is not None:
            self._on_fail[sender] = on_fail

    def clear(self):
        self._senders_by_symbol.clear()
        self._on_fail.clear()

    def symbols_of(self, sender: Sender[DataModel]) -> set[str]:
        """`sender`가 구독 중인 심볼."""

        return {symbol for symbol, senders in self._senders_by_symbol.items() if sender in senders}

    def drain(self) -> list[tuple[set[str], OnFail | None]]:
        """센더마다 (구독 심볼, 실패 콜백)을 돌려주고 라우터를 비운다. 스테이지 실패에 쓴다."""

        senders = {sender for senders in self._senders_by_symbol.values() for sender in senders}
        drained = [(self.symbols_of(sender), self._on_fail.get(sender)) for sender in senders]
        self.clear()
        return [(symbols, on_fail) for symbols, on_fail in drained if symbols]

    def take(self, symbols: set[str] | frozenset[str]) -> list[tuple[set[str], OnFail | None]]:
        """`symbols`의 구독만 떼고, 센더마다 (뗀 심볼, 실패 콜백)을 돌려준다. 심볼 실패에 쓴다.

        심볼이 모두 빠진 센더는 실패 콜백도 뺀다.
        """

        taken: dict[Sender[DataModel], set[str]] = {}
        for symbol in symbols:
            for sender in self._senders_by_symbol.pop(symbol, ()):
                taken.setdefault(sender, set()).add(symbol)
        result = [(removed, self._on_fail.get(sender)) for sender, removed in taken.items()]
        for sender in taken:
            if not self.symbols_of(sender):
                self._on_fail.pop(sender, None)
        return result

    async def __call__(self, data: DataModel):
        senders = list(self._senders_by_symbol.get(data.symbol, ()))
        if not senders:
            log.warning("데이터를 전송할 Sender가 없다", symbol=data.symbol)
            return
        # 한 Sender의 실패가 나머지 Sender와 이 라우터를 부른 공유 generator로 번지지 않게
        # 결과를 모아 따로 처리한다. `TaskGroup`은 하나가 던지면 형제를 취소하고 다시 던진다.
        results = await gather(*(sender(data) for sender in senders), return_exceptions=True)
        for sender, result in zip(senders, results, strict=True):
            if isinstance(result, Exception):
                await self.fail_sender(sender, result)
            elif isinstance(result, BaseException):
                raise result

    async def fail_sender(self, sender: Sender[DataModel], exc: Exception):
        """실패한 센더를 떼어 내고 그 센더의 실패 콜백을 부른다.

        이미 빠진 센더면 아무것도 안 한다.
        """

        symbols = self.symbols_of(sender)
        if not symbols:
            return
        on_fail = self._on_fail.get(sender)
        self.remove(sender)
        if on_fail is None:
            log.error("Sender가 실패해 구독에서 뗐다", symbols=sorted(symbols), exc_info=exc)
            return
        await on_fail(symbols, exc)

    @property
    def symbols(self) -> set[str]:
        """구독자가 하나라도 있는 심볼의 합집합."""

        return {symbol for symbol, senders in self._senders_by_symbol.items() if senders}


class UpstreamRoute(NamedTuple):
    content_id: str
    upstream: BaseRequest
    router: SymbolRouter


class UpstreamRouters:
    """상위 요청(content_id)마다 `SymbolRouter` 하나를 유지한다."""

    def __init__(self):
        # `UpstreamRoute`는 요청 모델을 품고 있어 해시할 수 없다. content_id를 키로 쓴다.
        self._routes: dict[str, UpstreamRoute] = {}

    def add_sender(self, upstream: BaseRequest, sender: PipelineSender):
        content_id = upstream.tr_content_id
        route = self._routes.get(content_id)
        if route is None:
            route = UpstreamRoute(content_id, upstream, SymbolRouter())
            self._routes[content_id] = route
        route.router.add(sender, sender.pipeline.upstream_symbol)

    def clear(self):
        # 라우터만 비우고 `UpstreamRoute`는 남긴다. content_id마다 같은 `SymbolRouter`
        # 객체가 유지되어야 구독에 등록된 `Sender`와 동일성이 깨지지 않는다.
        for route in self._routes.values():
            route.router.clear()

    def prune(self):
        """센더가 하나도 남지 않은 항목을 지운다. `clear()` 뒤 다시 채운 다음에 부른다.

        지운 항목의 상위 구독은 같은 갱신에서 떼어 내므로, 나중에 같은 content_id가
        다시 쓰이면 새 `SymbolRouter`와 새 구독이 짝지어져 동일성 검사가 깨지지 않는다.
        """

        for content_id in [c for c, route in self._routes.items() if not route.router.symbols]:
            del self._routes[content_id]

    def __iter__(self) -> Iterator[UpstreamRoute]:
        return iter(list(self._routes.values()))
