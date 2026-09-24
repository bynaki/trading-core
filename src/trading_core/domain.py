from asyncio import Lock, TaskGroup
from collections.abc import AsyncGenerator, Coroutine
from contextlib import aclosing, asynccontextmanager
from typing import Any

from .binder import BindPack
from .exceptions import ChannelClosed, DomainError, StageError
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
from .routing import Channel, PipelineSender, SymbolRouter, UpstreamRouters
from .tasks import TaskManager

_ALWAYS_SLOT = "__always__"
"""세션 요청의 `always` 파이프라인이 쓰는 슬롯 키. bind된 적이 없으므로 unbind 대상이 아니다."""


class _StageCreationKey:
    pass


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
        raise StageError("'update()'가 구현되지 않았다.")

    async def detach(self) -> None:
        raise StageError("'detach()'가 구현되지 않았다.")


class SharedStage[T: BaseRequest](BaseStage[T]):
    """content_id가 같은 원천·파생 요청이 공유하는 스테이지."""

    def __init__(self, key: _StageCreationKey, /, id: str, request: T) -> None:
        super().__init__(key, id, request)
        self._router = SymbolRouter()

    async def update(self, sender: Sender, symbols: set[str]) -> None:
        raise StageError("'update()'가 구현되지 않았다.")

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
    def __init__(self) -> None:
        self._tasks = TaskManager()
        self._shared_stages: dict[str, SharedStage] = {}
        self._stage_seq = 0

    @asynccontextmanager
    async def subscribe(self, req: BaseRequest, sender: Sender):
        """`req`를 구독하고 데이터를 `sender`로 받는다. 블록을 벗어나면 구독을 끊는다."""
        sub = self._create_subscription(req, sender)
        try:
            yield sub
        finally:
            await sub.detach()

    def stream(self, req: BaseRequest, symbols: set[str]):
        """`req`를 `symbols`로 구독해 데이터를 흘려주는 async generator."""
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

    async def _ensure_upstream_stage(
        self, upstream: BaseRequest, sender: Sender[DataModel], symbols: set[str]
    ):
        content_id = upstream.tr_content_id
        stage = self._shared_stages.get(content_id)
        if stage is None:
            if not symbols:
                return
            if is_source(upstream):
                stage = self._get_or_create_source_stage(upstream)
            elif is_derived(upstream):
                stage = self._get_or_create_derived_stage(upstream)
            else:
                raise DomainError(
                    "상위 요청은 `SourceRequest` 이거나 `DerivedRequest` 이어야 한다."
                )
        await stage.update(sender, symbols)

    def _create_source_subscription(self, req: BaseRequest, sender: Sender):
        sub = Subscription(
            _STAGE_CREATION_KEY,
            id=self._next_stage_id(req),
            request=req,
            sender=sender,
        )

        async def update(symbols: set[str]):
            stage = self._get_or_create_source_stage(req)
            await stage.update(sender, symbols)

        async def detach():
            stage = self._shared_stages.get(sub.request.tr_content_id)
            if stage:
                await stage.update(sub.sender, set())
            _mark_detached(sub)

        sub.update = update
        sub.detach = detach
        return sub

    def _get_or_create_source_stage(self, req: BaseRequest):
        stage_id = self._next_stage_id(req)
        content_id = req.tr_content_id
        if stage := self._shared_stages.get(content_id):
            return stage
        bind_pack = self._get_bind_pack(get_model_id(req))
        ctx = bind_pack.get_init_cb()(req)
        stage = SharedStage(
            _STAGE_CREATION_KEY,
            id=stage_id,
            request=req,
        )
        router = stage.router
        gen: AsyncGenerator[DataModel] | None = None
        update_lock = Lock()
        active_symbols: set[str] | None = None
        source_cb = bind_pack.get_source_cb(req)
        if source_cb is None:
            raise StageError(f"'source_cb'가 'bind'되지 않았다. - {get_model_id(req)}")

        async def update(sender: Sender, symbols: set[str]):
            nonlocal active_symbols, gen
            async with update_lock:
                router.replace(sender, symbols)
                current_symbols = router.symbols
                if current_symbols == active_symbols:
                    return
                if gen:
                    await self._cancel_by_name(stage_id)
                    await gen.aclose()
                    gen = None
                # 업데이트 심볼이 없다면 자원 정리한다.
                if not current_symbols:
                    self._shared_stages.pop(content_id, None)
                    if detach_cb := bind_pack.get_detach_cb():
                        await detach_cb(ctx)
                    active_symbols = current_symbols
                    return
                gen = source_cb(ctx, set(current_symbols))

                async def _pump(gen: AsyncGenerator[DataModel]):
                    async for data in gen:
                        await router(data)

                await self._submit(_pump(gen), stage_id)
                active_symbols = current_symbols

        stage.update = update
        self._shared_stages[content_id] = stage
        return stage

    def _create_derived_subscription(self, req: BaseRequest, sender: Sender):
        sub = Subscription(
            _STAGE_CREATION_KEY,
            id=self._next_stage_id(req),
            request=req,
            sender=sender,
        )

        async def update(symbols: set[str]):
            stage = self._get_or_create_derived_stage(req)
            await stage.update(sender, symbols)

        async def detach():
            stage = self._shared_stages.get(sub.request.tr_content_id)
            if stage:
                await stage.update(sub.sender, set())
            _mark_detached(sub)

        sub.update = update
        sub.detach = detach
        return sub

    def _get_or_create_derived_stage(self, req: BaseRequest):
        stage_id = self._next_stage_id(req)
        content_id = req.tr_content_id
        if stage := self._shared_stages.get(content_id):
            return stage
        bind_pack = self._get_bind_pack(get_model_id(req))
        ctx = bind_pack.get_init_cb()(req)
        stage = SharedStage(
            _STAGE_CREATION_KEY,
            id=stage_id,
            request=req,
        )
        router = stage.router
        gen: AsyncGenerator[DataModel] | None = None
        channel = Channel[DataModel]()
        update_lock = Lock()
        active_symbols: set[str] | None = None

        if not isinstance(req, DerivedRequest):
            raise StageError(f"'DerivedRequest'이어야 한다. - {get_model_id(req)}")
        derived_cb = bind_pack.get_derived_cb(req)
        if derived_cb is None:
            raise StageError(f"'derived_cb'가 'bind'되지 않았다. - {get_model_id(req)}")

        async def update(sender: Sender, symbols: set[str]):
            nonlocal active_symbols, gen
            async with update_lock:
                router.replace(sender, symbols)
                current_symbols = router.symbols
                if current_symbols == active_symbols:
                    return
                # 상위에 등록하는 심볼도 이 스테이지의 합집합이어야 한다. 이번
                # update의 symbols만 넘기면 같은 channel의 이전 등록을 덮어써
                # 먼저 구독한 쪽이 상위에서 사라진다.
                upstream, upstream_symbols = req.resolve_upstream(current_symbols)
                if gen:
                    await self._cancel_by_name(stage_id)
                    await gen.aclose()
                    gen = None
                # 업데이트 심볼이 없다면 자원 정리한다.
                if not current_symbols:
                    await self._ensure_upstream_stage(upstream, channel, set())
                    self._shared_stages.pop(content_id, None)
                    if detach_cb := bind_pack.get_detach_cb():
                        await detach_cb(ctx)
                    active_symbols = current_symbols
                    return
                await self._ensure_upstream_stage(upstream, channel, upstream_symbols)
                gen = derived_cb(ctx, set(current_symbols), channel.recv)

                async def _pump(gen: AsyncGenerator[DataModel]):
                    async for data in gen:
                        await router(data)

                await self._submit(_pump(gen), stage_id)
                active_symbols = current_symbols

        stage.update = update
        self._shared_stages[content_id] = stage
        return stage

    def _create_session_subscription(self, req: BaseRequest, sender: Sender):
        stage_id = self._next_stage_id(req)
        sub = Subscription(
            _STAGE_CREATION_KEY,
            id=stage_id,
            request=req,
            sender=sender,
        )
        model_id = get_model_id(req)
        bind_pack = self._get_bind_pack(model_id)
        bind_cb = bind_pack.get_bind_cb()
        unbind_cb = bind_pack.get_unbind_cb()
        detach_cb = bind_pack.get_detach_cb()
        always_cb = bind_pack.get_always_cb()
        if bind_cb is None:
            raise DomainError(f"`@bind`는 바인드 되어야 한다. - {model_id}")
        ctx = bind_pack.get_init_cb()(req)
        slot_channels: dict[str, Channel[tuple[DataModel, Pipeline]]] = {}
        slot_senders: dict[str, set[PipelineSender]] = {}
        upstream_routers = UpstreamRouters()
        upstream_subs: set[Subscription] = set()
        update_lock = Lock()

        async def open_slot(slot: str, pipelines: AsyncGenerator[Pipeline]) -> None:
            """슬롯 채널을 열고 파이프라인마다 센더를 만든 뒤 슬롯 태스크를 띄운다."""

            channel = Channel[tuple[DataModel, Pipeline]]()
            slot_channels[slot] = channel
            senders: set[PipelineSender] = set()
            async for pipeline in pipelines:
                senders.add(PipelineSender(channel, pipeline))
            slot_senders[slot] = senders
            await self._submit(self._run_pipeline_slot(channel.recv, sender), f"{stage_id}:{slot}")

        async def close_slots(target: set[str]) -> None:
            """슬롯을 닫고 슬롯 태스크가 끝나 이름을 놓을 때까지 기다린다.

            큐만 닫으면 태스크가 전송(`sender`)에 묶여 있는 동안 `{stage_id}:{symbol}` 이름이
            점유된 채 남아, 같은 심볼을 곧바로 다시 열 때 이름 충돌이 난다.
            """

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

            if not target:
                return
            await close_slots(target)
            if unbind_cb:
                async with TaskGroup() as tg:
                    for symbol in target:
                        tg.create_task(unbind_cb(ctx, symbol))

        async def update(symbols: set[str]):
            nonlocal always_cb, upstream_subs
            async with update_lock:
                active_symbols: set[str] = set(slot_channels.keys())
                current_symbols: set[str] = symbols | {_ALWAYS_SLOT}
                await unbind_symbols(active_symbols - current_symbols)
                if always_cb:
                    await open_slot(_ALWAYS_SLOT, always_cb(ctx))
                    always_cb = None
                # `current_symbols`는 센티널을 지우지 않으려고 만든 것이라 여기에
                # 쓰면 안 된다. `_ALWAYS_SLOT` 슬롯은 위 `always_cb` 분기만 만든다.
                for symbol in symbols - active_symbols:
                    await open_slot(symbol, bind_cb(ctx, symbol))
                upstream_routers.clear()
                for senders in slot_senders.values():
                    for pipeline_sender in senders:
                        upstream_routers.add_sender(
                            pipeline_sender.pipeline.upstream, pipeline_sender
                        )
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
                                raise DomainError(
                                    "불변 조건의 오류: 두 `Sender`는 같은 객체여야 한다."
                                )
                            upstream_sub = active
                            break
                    if upstream_sub is None:
                        upstream_sub = self._create_subscription(route.upstream, route.router)
                    current_subs.add(upstream_sub)
                    # 상위에 등록할 심볼은 파이프라인이 요구한 상위 표기(`upstream_symbol`)다.
                    # 이 구독이 받은 하위 심볼이 아니다.
                    updating.append((upstream_sub, route.router.symbols))
                async with TaskGroup() as tg:
                    for detaching in upstream_subs - current_subs:
                        tg.create_task(detaching.detach())
                async with TaskGroup() as tg:
                    for upstream_sub, upstream_symbols in updating:
                        tg.create_task(upstream_sub.update(upstream_symbols))
                upstream_subs = current_subs

        async def detach():
            # `bind_cb`로 연 슬롯은 모두 짝을 맞춰 닫는다. `_ALWAYS_SLOT`은 `always_cb`가
            # 만든 슬롯이라 bind된 적이 없으므로 제외한다.
            await unbind_symbols(set(slot_channels) - {_ALWAYS_SLOT})
            await close_slots(set(slot_channels))  # 남은 것은 `_ALWAYS_SLOT` 슬롯뿐이다
            async with TaskGroup() as tg:
                for upstream_sub in upstream_subs:
                    tg.create_task(upstream_sub.detach())
            if detach_cb:
                await detach_cb(ctx)
            _mark_detached(sub)

        sub.update = update
        sub.detach = detach
        return sub

    def _create_subscription(self, req: BaseRequest, sender: Sender):
        if is_source(req):
            return self._create_source_subscription(req, sender)
        if is_derived(req):
            return self._create_derived_subscription(req, sender)
        if is_session(req):
            return self._create_session_subscription(req, sender)
        raise DomainError(
            f"지원 되는 요청이 아니거나 등록된 요청이 아니다. - {get_model_type(req)}"
        )

    async def _run_pipeline_slot(
        self, recv: Receiver[tuple[DataModel, Pipeline]], sender: Sender[DataModel]
    ):
        while True:
            try:
                data, pipeline = await recv()
            except ChannelClosed:
                break
            out_data = await pipeline.invoke(data)
            if out_data:
                if not out_data.get_tr_req_content_id():
                    out_data._tr_req_content_id = pipeline.upstream.tr_content_id
                await sender(out_data)

    async def _stream_impl(self, req: BaseRequest, symbols: set[str]):
        channel = Channel()
        async with self.subscribe(req, channel) as sub:
            await sub.update(symbols)
            while True:
                yield await channel.recv()

    async def _submit(self, coro: Coroutine[Any, Any, None], name: str):
        return await self._tasks.submit(coro, name)

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
