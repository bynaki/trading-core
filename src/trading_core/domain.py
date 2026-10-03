from asyncio import Lock, TaskGroup, current_task, gather
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Iterable
from contextlib import aclosing, asynccontextmanager
from typing import Any

from .binder import BindPack
from .exceptions import ChannelClosed, DomainError, StageFailed, SymbolRejected
from .logger import get_logger
from .model import (
    BaseRequest,
    DataModel,
    DerivedRequest,
    Pipeline,
    Receiver,
    Sender,
    get_model_id,
    get_model_type,
    is_derived,
    is_session,
    is_source,
)
from .routing import Channel, OnFail, PipelineSender, SymbolRouter, UpstreamRouters
from .tasks import TaskManager

log = get_logger(__name__)

_ALWAYS_SLOT = "__always__"
"""세션 요청의 `always` 파이프라인이 쓰는 슬롯 키. bind된 적이 없으므로 unbind 대상이 아니다."""

type OnError = Callable[[StageFailed], Awaitable[None]]
"""구독의 일부 또는 전체가 실패했을 때 소비자가 받는 콜백."""


class _StageCreationKey:
    pass


class _InitFailed(Exception):
    """공유 스테이지를 만들다 init 콜백이 던졌다. binder 누락 같은 `DomainError`와 가르려고 쓴다."""

    def __init__(self, exc: Exception) -> None:
        super().__init__(exc)
        self.exc = exc


_STAGE_CREATION_KEY = _StageCreationKey()


class BaseStage[T: BaseRequest]:
    def __init__(self, key: _StageCreationKey, /, id: str, request: T) -> None:
        if key is not _STAGE_CREATION_KEY:
            raise TypeError("구독과 스테이지는 'Domain'을 통해서만 생성할 수 있다.")
        self._id = id
        self._request = request

    @property
    def id(self) -> str:
        return self._id

    @property
    def request(self) -> T:
        return self._request


class Subscription[T: BaseRequest](BaseStage[T]):
    """`Domain.subscribe()`가 돌려주는 구독. `update()`로 심볼을 바꾸고 `detach()`로 끊는다."""

    def __init__(self, key: _StageCreationKey, /, id: str, request: T, sender: Sender) -> None:
        super().__init__(key, id, request)
        self._sender = sender

    @property
    def sender(self) -> Sender:
        return self._sender

    async def update(self, symbols: set[str]) -> None:
        """구독 심볼을 `symbols`로 바꾼다. 빈 집합이면 구독이 사라진다."""
        raise NotImplementedError("'update()'는 'Domain'이 채운다.")

    async def detach(self) -> None:
        raise NotImplementedError("'detach()'는 'Domain'이 채운다.")


class SharedStage[T: BaseRequest](BaseStage[T]):
    """content_id가 같은 원천·파생 요청이 공유하는 스테이지."""

    def __init__(self, key: _StageCreationKey, /, id: str, request: T) -> None:
        super().__init__(key, id, request)
        self._router = SymbolRouter()

    async def update(
        self, sender: Sender, symbols: set[str], on_fail: OnFail | None = None
    ) -> None:
        raise NotImplementedError("'update()'는 'Domain'이 채운다.")

    async def refresh(self) -> None:
        """라우터에서 센더가 빠졌을 때 합집합을 다시 계산해 필요하면 재시작한다."""
        raise NotImplementedError("'refresh()'는 'Domain'이 채운다.")

    @property
    def router(self) -> SymbolRouter:
        return self._router


def _mark_detached(sub: Subscription) -> None:
    """끊긴 구독의 `update()`·`detach()`가 `DomainError`를 던지게 한다."""

    async def detached_update(symbols: set[str]):
        raise DomainError("이미 `detach`되었다.")

    async def detached_detach():
        raise DomainError("이미 `detach`되었다.")

    sub.update = detached_update
    sub.detach = detached_detach


class Domain:
    """요청을 구독으로 바꿔 실행한다.

    실패 정책: 코어는 재시도하지 않는다. init·bind 콜백, generator·파이프라인·Sender가 던지면 그
    스테이지나 슬롯을 내리고(init이면 세우지 않고), 영향을 받은 소비자에게 **자기 심볼만** 담은
    `StageFailed`를 알린다. 실패한
    심볼은 구독에서 빠지고, 소비자는 `update()`로 다시 넣을 수 있다. 무해한 끊김을 버틸지는
    binder가 generator 안에서 스스로 정한다. 정리 콜백(`detach`·`unbind`, generator의
    `finally`)의 실패는 정리를 끝까지 한 뒤 로그로만 남기고 호출자에게 올리지 않는다.
    """

    def __init__(self) -> None:
        self._tasks = TaskManager()
        self._shared_stages: dict[str, SharedStage] = {}
        self._stage_seq = 0
        self._spawn_seq = 0

    @asynccontextmanager
    async def subscribe(self, req: BaseRequest, sender: Sender, on_error: OnError | None = None):
        """`req`를 구독하고 데이터를 `sender`로 받는다. 블록을 벗어나면 구독을 끊는다.

        구독의 일부 또는 전체가 실패하면 `on_error`로 `StageFailed`를 받는다. 없으면 로그만 남는다.
        """
        sub = self._create_subscription(req, sender, on_error)
        try:
            yield sub
        finally:
            await sub.detach()

    def stream(self, req: BaseRequest, symbols: set[str]):
        """`req`를 `symbols`로 구독해 데이터를 흘려주는 async generator.

        구독이 실패하면 `StageFailed`를 던지고 끝난다.
        """
        return aclosing(self._stream_impl(req, symbols))

    async def start(self):
        return await self._tasks.start()

    async def wait(self):
        return await self._tasks.wait()

    async def stop(self):
        return await self._tasks.stop()

    def get_shared_symbols(self, content_id: str) -> set[str]:
        """content_id로 공유 중인 스테이지의 구독 심볼 합집합. 공유 중이 아니면 빈 집합이다."""
        stage = self._shared_stages.get(content_id)
        if stage is None:
            return set()
        return set(stage.router.symbols)

    async def _update_shared_stage(
        self,
        req: BaseRequest,
        sender: Sender[DataModel],
        symbols: set[str],
        on_fail: OnFail | None = None,
    ) -> bool:
        """`req`의 공유 스테이지에서 `sender`의 구독을 `symbols`로 바꾼다. 없으면 만든다.

        빈 집합으로는 스테이지를 새로 만들지 않는다. 만들면 init 콜백이 불렸다가 곧바로
        detach된다. 스테이지를 만들다 init 콜백이 던지면 스테이지를 두지 않고 `on_fail`로
        `symbols`의 실패를 알린 뒤 `False`를 돌려준다.
        """

        stage = self._shared_stages.get(req.tr_content_id)
        if stage is None:
            if not symbols:
                return True
            try:
                stage = self._get_or_create_shared_stage(req)
            except _InitFailed as failed:
                log.error(
                    "init 콜백이 실패했다",
                    request=get_model_id(req),
                    content_id=req.tr_content_id,
                    symbols=sorted(symbols),
                    exc_info=failed.exc,
                )
                if on_fail is not None:
                    await on_fail(set(symbols), failed.exc)
                return False
        await stage.update(sender, symbols, on_fail)
        return True

    def _create_shared_subscription(
        self, req: BaseRequest, sender: Sender, on_error: OnError | None
    ):
        sub = Subscription(
            _STAGE_CREATION_KEY,
            id=self._next_stage_id(req),
            request=req,
            sender=sender,
        )

        async def update(symbols: set[str]):
            on_fail = self._subscriber_on_fail(req.tr_content_id, sender, on_error)
            await self._update_shared_stage(req, sender, symbols, on_fail)

        async def detach():
            try:
                await self._update_shared_stage(req, sender, set())
            finally:
                _mark_detached(sub)

        sub.update = update
        sub.detach = detach
        return sub

    def _get_or_create_shared_stage(self, req: BaseRequest) -> SharedStage:
        content_id = req.tr_content_id
        if stage := self._shared_stages.get(content_id):
            return stage
        stage_id = self._next_stage_id(req)
        bind_pack = self._get_bind_pack(get_model_id(req))
        source_cb = derived_cb = derived_req = None
        if is_source(req):
            source_cb = bind_pack.get_source_cb(req)
            if source_cb is None:
                raise DomainError(
                    f"불변 조건의 오류: 'source_cb'가 'bind'되지 않았다. - {get_model_id(req)}"
                )
        elif is_derived(req):
            if not isinstance(req, DerivedRequest):
                raise DomainError(
                    f"불변 조건의 오류: 'DerivedRequest'이어야 한다. - {get_model_id(req)}"
                )
            derived_req = req
            derived_cb = bind_pack.get_derived_cb(req)
            if derived_cb is None:
                raise DomainError(
                    f"불변 조건의 오류: 'derived_cb'가 'bind'되지 않았다. - {get_model_id(req)}"
                )
        else:
            raise DomainError(
                "공유 스테이지는 `SourceRequest` 이거나 `DerivedRequest` 이어야 한다."
            )
        try:
            ctx = bind_pack.get_init_cb()(req)
        except Exception as exc:
            raise _InitFailed(exc) from exc
        detach_cb = bind_pack.get_detach_cb()
        stage = SharedStage(
            _STAGE_CREATION_KEY,
            id=stage_id,
            request=req,
        )
        router = stage.router
        channel = Channel[DataModel]()  # 파생만 쓴다: 상위 데이터를 받는 곳
        upstream: BaseRequest | None = None  # 파생만 쓴다: 지금 등록된 상위 요청
        update_lock = Lock()
        active_symbols: set[str] | None = None
        run_seq = 0  # generator를 새로 띄울 때마다 는다. 지난 generator의 실패를 가려낸다.
        retired = False  # 비었거나 실패해 `_shared_stages`에서 빠졌다

        async def update(sender: Sender, symbols: set[str], on_fail: OnFail | None = None):
            async with update_lock:
                if not retired:
                    router.replace(sender, symbols, on_fail)
                    await sync()
                    return
            # 빠지기 직전의 이 스테이지를 잡고 락을 기다리던 호출이다. 여기서 generator를 띄우면
            # 아무도 찾지 못하는 스테이지가 되므로 지금 등록된 스테이지로 넘긴다(없고 심볼이
            # 있으면 새로 만든다).
            await self._update_shared_stage(req, sender, symbols, on_fail)

        async def refresh():
            async with update_lock:
                if not retired:
                    await sync()

        async def sync():
            """라우터의 합집합이 바뀌었으면 generator를 다시 띄운다. 락 안에서 부른다."""

            nonlocal active_symbols, run_seq, upstream
            current_symbols = router.symbols
            if current_symbols == active_symbols:
                return
            await self._cancel_by_name(stage_id)  # generator는 `pump()`가 닫는다
            run_seq += 1
            # 업데이트 심볼이 없다면 자원 정리한다.
            if not current_symbols:
                await retire()
                return
            if derived_req is not None and derived_cb is not None:
                # 상위에 등록하는 심볼도 이 스테이지의 합집합이어야 한다. 이번 update의
                # symbols만 넘기면 같은 channel의 이전 등록을 덮어써 먼저 구독한 쪽이 상위에서
                # 사라진다.
                upstream, upstream_symbols = derived_req.resolve_upstream(current_symbols)
                if not await self._update_shared_stage(
                    upstream, channel, upstream_symbols, on_upstream_fail(upstream)
                ):
                    # 상위를 세우지 못했다(init 실패). `on_upstream_fail()`이 띄운 태스크가 이
                    # 스테이지를 실패로 내리므로 generator를 띄우지 않는다.
                    return
                gen = derived_cb(ctx, set(current_symbols), channel.recv)
            else:
                assert source_cb is not None
                gen = source_cb(ctx, set(current_symbols))
            await self._submit(pump(gen, run_seq), stage_id)
            active_symbols = current_symbols

        async def retire():
            """스테이지를 레지스트리에서 빼고 자원을 정리한다. 락 안에서 부른다."""

            nonlocal retired, active_symbols
            retired = True
            active_symbols = set()
            if self._shared_stages.get(content_id) is stage:
                del self._shared_stages[content_id]
            if upstream is not None:
                await self._update_shared_stage(upstream, channel, set())
            if detach_cb:
                await self._run_cleanups("detach", [detach_cb(ctx)])

        async def fail(exc: Exception) -> list[tuple[set[str], OnFail | None]]:
            """재시도 없이 스테이지를 내리고 알릴 소비자를 돌려준다. 락 안에서 부른다."""

            await self._cancel_by_name(stage_id)
            await retire()
            drained = router.drain()
            log.error(
                "스테이지가 실패했다",
                stage=stage_id,
                symbols=sorted(set().union(*(symbols for symbols, _ in drained))),
                exc_info=exc,
            )
            return drained

        async def fail_symbols(
            symbols: set[str] | frozenset[str], exc: Exception
        ) -> list[tuple[set[str], OnFail | None]]:
            """`symbols`만 구독에서 빼고 남은 심볼로 다시 띄운다. 락 안에서 부른다.

            알릴 소비자를 돌려준다. 남은 심볼이 없으면 `sync()`가 스테이지를 내린다.
            """

            taken = router.take(symbols)
            log.error(
                "심볼이 실패해 구독에서 뺐다", stage=stage_id, symbols=sorted(symbols), exc_info=exc
            )
            await sync()
            return taken

        async def fail_and_notify(exc: Exception, seq: int | None = None):
            async with update_lock:
                if retired or (seq is not None and seq != run_seq):
                    # 그 사이 `update()`가 generator를 새로 띄웠거나 스테이지가 이미 내려갔다.
                    log.error("지난 generator가 실패했다", stage=stage_id, exc_info=exc)
                    return
                rejected = (
                    exc.symbols & router.symbols if isinstance(exc, SymbolRejected) else set()
                )
                if rejected:
                    drained = await fail_symbols(rejected, exc)
                else:
                    # 다른 예외이거나, 지금 구독되지 않은 심볼만 거부했다. 후자를 같은 합집합으로
                    # 다시 띄우면 끝없이 되풀이되므로 스테이지 전체의 실패로 본다.
                    drained = await fail(exc)
            await notify(drained, exc)

        async def fail_upstream_symbols(failed: StageFailed):
            """상위가 실패한 심볼(상위 표기)을 쓰는 하위 심볼만 내린다. 파생만 쓴다.

            상위 스테이지 전체가 실패했으면 모든 하위 심볼이 걸려 이 스테이지도 전체가 실패한다.
            """

            assert derived_req is not None
            async with update_lock:
                if retired:
                    return
                current = router.symbols
                # 하위 심볼마다 상위 표기를 구해 되돌린다. require 콜백이 심볼을 하나씩
                # 바꾼다고 본다.
                lower = {
                    symbol
                    for symbol in current
                    if derived_req.resolve_upstream({symbol})[1] & failed.symbols
                }
                if lower and lower != current:
                    drained = await fail_symbols(lower, failed)
                else:
                    # 모두 걸렸거나, 되돌리지 못했다. 후자를 그냥 두면 그 심볼이 소리 없이
                    # 굶으므로 스테이지 전체의 실패로 본다.
                    drained = await fail(failed)
            await notify(drained, failed)

        async def notify(drained: list[tuple[set[str], OnFail | None]], exc: Exception):
            for symbols, on_fail in drained:
                if on_fail is not None:
                    await on_fail(symbols, exc)

        def on_upstream_fail(upstream: BaseRequest) -> OnFail:
            upstream_content_id = upstream.tr_content_id

            async def on_fail(symbols: set[str], exc: Exception):
                failed = StageFailed.from_exception(upstream_content_id, symbols, exc)
                await self._spawn(fail_upstream_symbols(failed), f"{stage_id}:upstream-failed")

            return on_fail

        async def pump(gen: AsyncGenerator[DataModel], seq: int):
            try:
                async with aclosing(gen):
                    async for data in gen:
                        await router(data)
            except Exception as exc:
                task = current_task()
                if task is not None and task.cancelling():
                    # 취소되며 generator를 닫는 중에 binder의 `finally`가 던졌다.
                    log.error("generator를 닫다가 실패했다", stage=stage_id, exc_info=exc)
                    return
                await self._spawn(fail_and_notify(exc, seq), f"{stage_id}:failed")

        stage.update = update
        stage.refresh = refresh
        self._shared_stages[content_id] = stage
        return stage

    def _create_session_subscription(
        self, req: BaseRequest, sender: Sender, on_error: OnError | None
    ):
        stage_id = self._next_stage_id(req)
        sub = Subscription(
            _STAGE_CREATION_KEY,
            id=stage_id,
            request=req,
            sender=sender,
        )
        model_id = get_model_id(req)
        bind_pack = self._get_bind_pack(model_id)
        init_cb = bind_pack.get_init_cb()
        bind_cb = bind_pack.get_bind_cb()
        unbind_cb = bind_pack.get_unbind_cb()
        detach_cb = bind_pack.get_detach_cb()
        always_cb = bind_pack.get_always_cb()
        if bind_cb is None:
            raise DomainError(f"`@bind`는 바인드 되어야 한다. - {model_id}")
        ctx = None  # 공유 스테이지처럼 첫 `update()`에서 만든다. init 실패도 거기서 알린다.
        always_armed = always_cb is not None  # 다음 `update()`에서 `always` 슬롯을 연다
        slot_channels: dict[str, Channel[tuple[DataModel, Pipeline]]] = {}
        slot_senders: dict[str, set[PipelineSender]] = {}
        upstream_routers = UpstreamRouters()
        upstream_subs: set[Subscription] = set()
        update_lock = Lock()

        async def notify(symbols: set[str], exc: Exception):
            if symbols:
                failed = StageFailed.from_exception(req.tr_content_id, symbols, exc)
                await self._notify(on_error, failed)

        async def open_slot(slot: str, pipelines: AsyncGenerator[Pipeline]) -> None:
            """파이프라인마다 센더를 만들고 슬롯 채널과 슬롯 태스크를 연다.

            파이프라인을 모두 받은 뒤에 등록하므로, 콜백이 도중에 던지면 슬롯은 열리지 않는다.
            """

            received = [pipeline async for pipeline in pipelines]
            channel = Channel[tuple[DataModel, Pipeline]]()
            slot_channels[slot] = channel
            slot_senders[slot] = {PipelineSender(channel, pipeline) for pipeline in received}

            async def on_slot_error(exc: Exception):
                async def handle():
                    async with update_lock:
                        if slot_channels.get(slot) is not channel:
                            return  # 그 사이 닫혔거나 다시 열린 슬롯이다
                        failed = await fail_slots({slot}, exc)
                    await notify(failed, exc)

                await self._spawn(handle(), f"{stage_id}:{slot}:failed")

            await self._submit(
                self._run_pipeline_slot(channel.recv, sender, on_slot_error), f"{stage_id}:{slot}"
            )

        async def close_slots(target: set[str]) -> None:
            """슬롯을 닫고 슬롯 태스크가 끝나 이름을 놓을 때까지 기다린다.

            큐만 닫으면 태스크가 전송(`sender`)에 묶여 있는 동안 `{stage_id}:{symbol}` 이름이
            점유된 채 남아, 같은 심볼을 곧바로 다시 열 때 이름 충돌이 난다.
            """

            target = target & slot_channels.keys()
            for slot in target:
                slot_channels.pop(slot).shutdown()
                slot_senders.pop(slot)
            async with TaskGroup() as tg:
                for slot in target:
                    tg.create_task(self._cancel_by_name(f"{stage_id}:{slot}"))

        async def unbind_symbols(target: set[str]) -> None:
            """슬롯을 닫고 심볼별 정리 콜백을 부른다. `update()`와 `detach()`가 함께 쓴다.

            `bind_cb`로 연 심볼은 어느 경로로 닫히든 `unbind_cb` 한 번으로 짝을 맞춘다.
            """

            target = target & slot_channels.keys()
            if not target:
                return
            await close_slots(target)
            if unbind_cb:
                await self._run_cleanups("unbind", [unbind_cb(ctx, symbol) for symbol in target])

        async def sync_upstreams() -> None:
            """열린 슬롯의 파이프라인에 맞춰 상위 구독을 붙이고 뗀다. 락 안에서 부른다."""

            nonlocal upstream_subs
            upstream_routers.clear()
            for senders in slot_senders.values():
                for pipeline_sender in senders:
                    upstream_routers.add_sender(pipeline_sender.pipeline.upstream, pipeline_sender)
            current_subs: set[Subscription] = set()
            updating: list[tuple[Subscription, set[str]]] = []
            # 어떤 파이프라인도 쓰지 않게 된 상위는 여기서 빠져 `current_subs`에 들지 않고
            # 아래에서 떼어진다. 남겨 두면 매 갱신마다 빈 집합으로 `update()`되어, 원천이
            # 이미 사라진 상위가 그때마다 새로 만들어졌다(init) 곧바로 정리된다.
            upstream_routers.prune()
            for route in upstream_routers:
                upstream_sub: Subscription | None = None
                for active in upstream_subs:
                    if active.request.tr_content_id == route.upstream.tr_content_id:
                        if active.sender != route.router:
                            raise DomainError("불변 조건의 오류: 두 `Sender`는 같은 객체여야 한다.")
                        upstream_sub = active
                        break
                if upstream_sub is None:
                    upstream_sub = self._create_subscription(
                        route.upstream, route.router, on_upstream_failed
                    )
                current_subs.add(upstream_sub)
                # 상위에 등록할 심볼은 파이프라인이 요구한 상위 표기(`upstream_symbol`)다.
                # 이 구독이 받은 하위 심볼이 아니다.
                updating.append((upstream_sub, route.router.symbols))
            await self._run_cleanups(
                "상위 구독 해제", [detaching.detach() for detaching in upstream_subs - current_subs]
            )
            async with TaskGroup() as tg:
                for upstream_sub, upstream_symbols in updating:
                    tg.create_task(upstream_sub.update(upstream_symbols))
            upstream_subs = current_subs

        async def fail_slots(slots: set[str], exc: Exception) -> set[str]:
            """슬롯을 실패로 닫고 실패한 하위 심볼을 돌려준다. 락 안에서 부른다.

            `always` 슬롯이 들면 모든 심볼이 실패한다. 이때는 컨텍스트도 정리해, 다음
            `update()`가 init 콜백부터 새로 시작한다.
            """

            nonlocal ctx, always_armed
            whole = _ALWAYS_SLOT in slots
            if whole:
                slots = set(slot_channels) | {_ALWAYS_SLOT}
            failed = slots - {_ALWAYS_SLOT}
            await unbind_symbols(failed)
            if whole:
                await close_slots({_ALWAYS_SLOT})
                if detach_cb and ctx is not None:
                    await self._run_cleanups("detach", [detach_cb(ctx)])
                ctx = None
                always_armed = always_cb is not None
            await sync_upstreams()
            log.error("세션 슬롯이 실패했다", stage=stage_id, symbols=sorted(failed), exc_info=exc)
            return failed

        async def on_upstream_failed(upstream_failed: StageFailed):
            async with update_lock:
                slots = {
                    slot
                    for slot, senders in slot_senders.items()
                    if any(
                        pipeline_sender.pipeline.upstream.tr_content_id
                        == upstream_failed.content_id
                        and pipeline_sender.pipeline.upstream_symbol in upstream_failed.symbols
                        for pipeline_sender in senders
                    )
                }
                if not slots:
                    return
                # 상위 표기로 온 실패를 슬롯 키(하위 표기)로 되돌려 알린다.
                failed = await fail_slots(slots, upstream_failed)
            await notify(failed, upstream_failed)

        async def update(symbols: set[str]):
            failures: list[tuple[set[str], Exception]] = []
            async with update_lock:
                await apply(symbols, failures)
            for failed_symbols, exc in failures:
                await notify(failed_symbols, exc)

        async def apply(symbols: set[str], failures: list[tuple[set[str], Exception]]) -> None:
            """슬롯을 `symbols`에 맞추고 실패한 (심볼, 원인)을 `failures`에 모은다.

            락 안에서 부른다. 알림은 락을 놓은 뒤 `update()`가 한다.
            """

            nonlocal ctx, always_armed
            if ctx is None:
                # 컨텍스트가 없으면 열린 슬롯도 없으므로 요청한 심볼이 모두 실패한다.
                try:
                    ctx = init_cb(req)
                except Exception as exc:
                    log.error(
                        "init 콜백이 실패했다",
                        stage=stage_id,
                        symbols=sorted(symbols),
                        exc_info=exc,
                    )
                    failures.append((set(symbols), exc))
                    return
            active_symbols: set[str] = set(slot_channels.keys())
            current_symbols: set[str] = symbols | {_ALWAYS_SLOT}
            await unbind_symbols(active_symbols - current_symbols)
            if always_armed and always_cb:
                always_armed = False
                try:
                    await open_slot(_ALWAYS_SLOT, always_cb(ctx))
                except Exception as exc:
                    unbound = await fail_slots({_ALWAYS_SLOT}, exc)
                    failures.append((unbound | symbols, exc))
                    return
            # `current_symbols`는 센티널을 지우지 않으려고 만든 것이라 여기에
            # 쓰면 안 된다. `_ALWAYS_SLOT` 슬롯은 위 `always_cb` 분기만 만든다.
            for symbol in symbols - active_symbols:
                try:
                    await open_slot(symbol, bind_cb(ctx, symbol))
                except Exception as exc:
                    log.error(
                        "심볼을 bind하지 못했다",
                        stage=stage_id,
                        symbol=symbol,
                        exc_info=exc,
                    )
                    failures.append(({symbol}, exc))
            await sync_upstreams()

        async def detach():
            try:
                async with update_lock:
                    # `bind_cb`로 연 슬롯은 모두 짝을 맞춰 닫는다. `_ALWAYS_SLOT`은 `always_cb`가
                    # 만든 슬롯이라 bind된 적이 없으므로 제외한다.
                    await unbind_symbols(set(slot_channels) - {_ALWAYS_SLOT})
                    await close_slots(set(slot_channels))  # 남은 것은 `_ALWAYS_SLOT` 슬롯뿐이다
                    await self._run_cleanups(
                        "상위 구독 해제", [upstream_sub.detach() for upstream_sub in upstream_subs]
                    )
                    upstream_subs.clear()
                    if detach_cb and ctx is not None:
                        await self._run_cleanups("detach", [detach_cb(ctx)])
            finally:
                _mark_detached(sub)

        sub.update = update
        sub.detach = detach
        return sub

    def _create_subscription(
        self, req: BaseRequest, sender: Sender, on_error: OnError | None = None
    ):
        if is_source(req) or is_derived(req):
            return self._create_shared_subscription(req, sender, on_error)
        if is_session(req):
            return self._create_session_subscription(req, sender, on_error)
        raise DomainError(
            f"지원 되는 요청이 아니거나 등록된 요청이 아니다. - {get_model_type(req)}"
        )

    def _subscriber_on_fail(
        self, content_id: str, sender: Sender, on_error: OnError | None
    ) -> OnFail:
        """공유 스테이지의 소비자 하나가 실패했을 때 부를 콜백을 만든다.

        스테이지 전체가 실패했거나, 이 소비자의 `sender`가 던져 라우터에서 빠진 경우다.
        """

        async def on_fail(symbols: set[str], exc: Exception):
            failed = StageFailed.from_exception(content_id, symbols, exc)

            async def handle():
                # `sender`만 빠졌다면 스테이지는 살아 있으니 줄어든 합집합으로 맞춘다.
                if stage := self._shared_stages.get(content_id):
                    await stage.refresh()
                await self._notify(on_error, failed)

            await self._spawn(handle(), f"{content_id}:failed")

        return on_fail

    async def _notify(self, on_error: OnError | None, failed: StageFailed):
        if on_error is None:
            log.error(
                "구독이 실패했다",
                content_id=failed.content_id,
                symbols=sorted(failed.symbols),
                cause=failed.cause,
            )
            return
        try:
            await on_error(failed)
        except Exception:
            log.exception("`on_error`가 실패했다", content_id=failed.content_id)

    async def _run_cleanups(self, what: str, coros: Iterable[Coroutine[Any, Any, None]]):
        """정리 코루틴을 모두 끝까지 돌리고, 실패는 로그로만 남긴다.

        `TaskGroup`과 달리 하나가 던져도 나머지를 취소하지 않는다.
        """

        results = await gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                log.error("정리 콜백이 실패했다", callback=what, exc_info=result)
            elif isinstance(result, BaseException):
                raise result

    async def _run_pipeline_slot(
        self,
        recv: Receiver[tuple[DataModel, Pipeline]],
        sender: Sender[DataModel],
        on_error: Callable[[Exception], Awaitable[None]],
    ):
        while True:
            try:
                data, pipeline = await recv()
            except ChannelClosed:
                break
            try:
                out_data = await pipeline.invoke(data)
                if out_data:
                    if not out_data.get_tr_req_content_id():
                        out_data._tr_req_content_id = pipeline.upstream.tr_content_id
                    await sender(out_data)
            except Exception as exc:
                await on_error(exc)
                return

    async def _stream_impl(self, req: BaseRequest, symbols: set[str]):
        channel = Channel()

        async def on_error(failed: StageFailed):
            await channel.send(failed)

        async with self.subscribe(req, channel, on_error) as sub:
            await sub.update(symbols)
            while True:
                item = await channel.recv()
                if isinstance(item, StageFailed):
                    raise item
                yield item

    async def _submit(self, coro: Coroutine[Any, Any, None], name: str):
        return await self._tasks.submit(coro, name)

    async def _spawn(self, coro: Coroutine[Any, Any, None], label: str):
        """이름이 겹치지 않게 번호를 붙여 태스크를 띄운다. 실패 처리처럼 한 번 도는 일에 쓴다."""
        self._spawn_seq += 1
        await self._submit(coro, f"{label}:{self._spawn_seq}")

    async def _cancel_by_name(self, name: str) -> bool:
        return await self._tasks.cancel_by_name(name)

    def _next_stage_id(self, req: BaseRequest):
        self._stage_seq += 1
        return f"{get_model_id(req)}:{self._stage_seq}"

    def _get_bind_pack(self, model_id: str) -> BindPack:
        bind_pack = BindPack.lookup(model_id)
        if bind_pack is None:
            raise DomainError(f"요청한 모델의 'Binder'를 찾을 수 없다. - {model_id}")
        return bind_pack
