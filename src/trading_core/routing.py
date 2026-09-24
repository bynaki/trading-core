from asyncio import Queue, QueueShutDown, TaskGroup
from collections.abc import Iterator
from typing import NamedTuple

from .exceptions import ChannelClosed, DomainError
from .logger import get_logger
from .model import BaseRequest, DataModel, Pipeline, Sender

log = get_logger(__name__)


class Channel[T]:
    """한 프로세스 안에서 데이터를 넘기는 큐. 호출하면 `send()`라 그대로 `Sender`로 쓸 수 있다."""

    def __init__(self):
        self._q = Queue[T]()

    async def send(self, data: T) -> None:
        try:
            return await self._q.put(data)
        except QueueShutDown as exc:
            raise ChannelClosed("'Channel'이 이미 닫혔다. - send()") from exc

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
    """상위 데이터를 그 데이터를 처리할 파이프라인과 함께 슬롯 채널로 보낸다."""

    def __init__(self, sender: Sender[tuple[DataModel, Pipeline]], pipeline: Pipeline):
        self._sender = sender
        self._pipeline = pipeline

    @property
    def pipeline(self):
        return self._pipeline

    async def __call__(self, data: DataModel):
        try:
            await self._sender((data, self._pipeline))
        except ChannelClosed:
            # 슬롯은 상위 구독이 갱신되기 전에 닫힌다. 그 사이 온 데이터는 받을 소비자가
            # 없으므로 버린다. 예외로 올리면 `SymbolRouter`를 거쳐 공유된 상위 generator가
            # 죽고, 다른 소비자가 같은 상위 심볼을 계속 구독 중이면 재시작되지도 않는다.
            pass


class SymbolRouter:
    """(Sender, 심볼) 구독을 모아 데이터를 `data.symbol`을 구독한 Sender에게만 보낸다."""

    def __init__(self):
        self._senders_by_symbol: dict[str, set[Sender[DataModel]]] = {}

    def add(self, sender: Sender[DataModel], symbol: str):
        if not symbol:
            raise DomainError("`symbol`은 한문자라도 있어야 한다.")
        senders = self._senders_by_symbol.setdefault(symbol, set())
        senders.add(sender)

    def remove(self, sender: Sender[DataModel], symbol: str = ""):
        if symbol:
            if senders := self._senders_by_symbol.get(symbol):
                senders.discard(sender)
        else:
            for senders in self._senders_by_symbol.values():
                senders.discard(sender)

    def replace(self, sender: Sender[DataModel], symbols: set[str]):
        """`sender`의 구독 심볼을 `symbols`로 바꾼다. 빈 집합이면 구독이 사라진다."""
        self.remove(sender)
        for symbol in symbols:
            self.add(sender, symbol)

    def clear(self):
        self._senders_by_symbol.clear()

    async def __call__(self, data: DataModel):
        sent = False
        if senders := self._senders_by_symbol.get(data.symbol):
            async with TaskGroup() as tg:
                for sender in senders:
                    tg.create_task(sender(data))
                    sent = True
        if not sent:
            log.warning("데이터를 전송할 Sender가 없다", symbol=data.symbol)

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
