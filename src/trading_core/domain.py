from asyncio import Lock, Queue, QueueShutDown, TaskGroup
from collections.abc import AsyncGenerator, Coroutine
from contextlib import aclosing, asynccontextmanager
from typing import Any, NamedTuple, cast

from .binder import (
    BindPack,
)
from .exceptions import ClosedConnection, DomainError, StageError
from .helper import TaskManager
from .model import (
    BaseReqModel,
    DataModel,
    DependentModel,
    Receiver,
    Sender,
    Sequence,
    get_model_id,
    get_model_type,
    is_dependent_model,
    is_generate_model,
    is_instant_model,
)


class TransmitQueue[T]:
    def __init__(self):
        self._q = Queue[T]()

    async def send(self, data: T) -> None:
        try:
            return await self._q.put(data)
        except QueueShutDown as exc:
            raise ClosedConnection("'TransmitQueue'가 이미 닫혔다. - send()") from exc

    async def __call__(self, data: T) -> None:
        return await self.send(data)

    async def recv(self) -> T:
        try:
            return await self._q.get()
        except QueueShutDown as exc:
            raise ClosedConnection("'TransmitQueue'가 이미 닫혔다. - recv()") from exc

    def shutdown(self):
        self._q.shutdown()


class SequenceSender:
    def __init__(self, sender: Sender[tuple[DataModel, Sequence]], seq: Sequence):
        self._sender = sender
        self._sequence = seq

    @property
    def origin_sender(self):
        return self._sender

    @property
    def sequence(self):
        return self._sequence

    async def __call__(self, data: DataModel):
        await self._sender((data, self._sequence))


class SendRouter:
    def __init__(self):
        self._route_dict: dict[str, set[Sender[DataModel]]] = {}

    def add(self, sender: Sender[DataModel], symbol: str):
        if not symbol:
            raise DomainError("`symbol`은 한문자라도 있어야 한다.")
        if tt := self._route_dict.get(symbol):
            ...
        else:
            tt = set()
            self._route_dict[symbol] = tt
        tt.add(sender)

    def remove(self, sender: Sender[DataModel], symbol: str = ""):
        if symbol:
            if ss := self._route_dict.get(symbol):
                ss.discard(sender)
        else:
            for ss in self._route_dict.values():
                ss.discard(sender)

    def set_sender(self, sender: Sender[DataModel], symbols: set[str]):
        self.remove(sender)
        for symbol in symbols:
            self.add(sender, symbol)

    def clear(self):
        self._route_dict.clear()

    async def __call__(self, data: DataModel):
        sent = False
        if sender_set := self._route_dict.get(data.symbol):
            async with TaskGroup() as tg:
                for sender in sender_set:
                    tg.create_task(sender(data))
                    sent = True
        if not sent:
            print(f"warning: 데이터를 전송할 'Sender'가 없다. - symbol: {data.symbol}")

    @property
    def symbols(self) -> set[str]:
        return {symbol for symbol, ss in self._route_dict.items() if ss}


class Registered(NamedTuple):
    content_id: str
    require: BaseReqModel
    router: SendRouter


class SendRouterSet:
    def __init__(self):
        # `Registered`는 요청 모델을 품고 있어 해시할 수 없다. content_id를 키로 쓴다.
        self._registered_dict: dict[str, Registered] = {}

    def add_sender(self, req: BaseReqModel, sender: SequenceSender):
        content_id = req.get_tr_content_id()
        reg = self._registered_dict.get(content_id)
        if reg is None:
            reg = Registered(content_id, req, SendRouter())
            self._registered_dict[content_id] = reg
        reg.router.add(sender, sender.sequence.symbol)

    def clear(self):
        # 라우터만 비우고 `Registered`는 남긴다. content_id마다 같은 `SendRouter`
        # 객체가 유지되어야 스테이지에 등록된 `Sender`와 동일성이 깨지지 않는다.
        for reg in self._registered_dict.values():
            reg.router.clear()

    def __call__(self):
        yield from self._registered_dict.values()


class _StageCreationKey:
    pass


_STAGE_CREATION_KEY = _StageCreationKey()


class BaseStage[T: BaseReqModel]:
    def __init__(self, key: _StageCreationKey, /, id: str, request: T, output: Sender) -> None:
        if key is not _STAGE_CREATION_KEY:
            raise TypeError("'Stage'는 'Domain'을 통해서만 생성할 수 있다.")
        self._id = id
        self._req_model = request
        self._output = output

    @property
    def id(self) -> str:
        return self._id

    @property
    def req_model(self) -> T:
        return self._req_model

    @property
    def output(self) -> Sender:
        return self._output


class Stage[T: BaseReqModel](BaseStage[T]):
    async def update(self, symbols: set[str]) -> None:
        raise StageError("'update()'가 구현되지 않았다.")

    async def detach(self) -> None:
        raise StageError("'detach()'가 구현되지 않았다.")


class OriginStage[T: BaseReqModel](BaseStage[T]):
    def __init__(self, key: _StageCreationKey, /, id: str, request: T) -> None:
        super().__init__(key, id, request, SendRouter())

    async def update(self, sender: Sender, symbols: set[str]) -> None:
        raise StageError("'update()'가 구현되지 않았다.")

    @property
    def output(self) -> SendRouter:
        return cast(SendRouter, self._output)


class Domain:
    def __init__(self) -> None:
        self._tmg = TaskManager()
        self._origin_stage_dict: dict[str, OriginStage] = {}
        self._count = 0

    @asynccontextmanager
    async def stage(self, req: BaseReqModel, output: Sender):
        stage = self._define_stage(req, output)
        try:
            yield stage
        finally:
            await stage.detach()

    def request(self, req: BaseReqModel, symbols: set[str]):
        return aclosing(self._gen_req(req, symbols))

    async def start(self):
        return await self._tmg.start()

    async def wait(self):
        return await self._tmg.wait()

    async def stop(self):
        return await self._tmg.stop()

    def get_origin_stage(self, content_id: str):
        return self._origin_stage_dict[content_id]

    async def _ensure_require_stage(
        self, req: BaseReqModel, sender: Sender[DataModel], symbols: set[str]
    ):
        content_id = req.get_tr_content_id()
        stage = self._origin_stage_dict.get(content_id)
        if stage is None:
            if not symbols:
                return
            if is_generate_model(req):
                stage = self._define_origin_gen_stage(req)
            elif is_dependent_model(req):
                stage = self._define_origin_dep_stage(req)
            else:
                raise DomainError(
                    "필요한 `Request Model`은 `GenerateModel` 이거나 `DependentModel` 이어야 한다."
                )
        await stage.update(sender, symbols)

    def _define_gen_stage(self, req: BaseReqModel, output: Sender):
        stage = Stage(
            _STAGE_CREATION_KEY,
            id=self._generate_id(req),
            request=req,
            output=output,
        )

        async def update(symbols: set[str]):
            origin_stage = self._define_origin_gen_stage(req)
            await origin_stage.update(output, symbols)

        async def detach():
            content_id = stage.req_model.get_tr_content_id()
            origin = self._origin_stage_dict.get(content_id)
            if origin:
                await origin.update(stage.output, set())
            stage.update = detached_update
            stage.detach = detached_detach

        async def detached_update(symbols: set[str]):
            raise DomainError("이미 `detach`되었다.")

        async def detached_detach():
            raise DomainError("이미 `detach`되었다.")

        stage.update = update
        stage.detach = detach
        return stage

    def _define_origin_gen_stage(self, req: BaseReqModel):
        id = self._generate_id(req)
        content_id = req.get_tr_content_id()
        if origin_stage := self._origin_stage_dict.get(content_id):
            return origin_stage
        model_id = get_model_id(req)
        bind_pack = self._get_bind_pack(model_id)
        ctx = bind_pack.get_init_cb()(req)
        stage = OriginStage(
            _STAGE_CREATION_KEY,
            id=id,
            request=req,
        )
        shared_sender = stage.output
        gen: AsyncGenerator[DataModel] | None = None
        update_lock = Lock()
        active_symbols: set[str] | None = None
        binded_cb = bind_pack.get_generate_cb(req)
        if binded_cb is None:
            raise StageError(f"'generator_cb'가 'bind'되지 않았다. - {get_model_id(req)}")

        async def update(sender: Sender, symbols: set[str]):
            nonlocal active_symbols, gen
            async with update_lock:
                shared_sender.set_sender(sender, symbols)
                current_symbols = shared_sender.symbols
                if current_symbols == active_symbols:
                    return
                if gen:
                    await self._cancel_by_name(id)
                    await gen.aclose()
                    gen = None
                # 업데이트 심볼이 없다면 자원 정리한다.
                if not current_symbols:
                    self._origin_stage_dict.pop(content_id, None)
                    if bind_pack._detach_cb:
                        await bind_pack._detach_cb(ctx)
                    active_symbols = current_symbols
                    return
                symbol_set = set(current_symbols)
                gen = binded_cb(ctx, symbol_set)

                async def _(gen: AsyncGenerator[DataModel]):
                    async for data in gen:
                        await shared_sender(data)

                await self._submit(_(gen), id)
                active_symbols = current_symbols

        stage.update = update
        self._origin_stage_dict[content_id] = stage
        return stage

    def _define_dep_stage(self, req: BaseReqModel, output: Sender):
        stage = Stage(
            _STAGE_CREATION_KEY,
            id=self._generate_id(req),
            request=req,
            output=output,
        )

        async def update(symbols: set[str]):
            origin_stage = self._define_origin_dep_stage(req)
            await origin_stage.update(output, symbols)

        async def detach():
            content_id = stage.req_model.get_tr_content_id()
            origin = self._origin_stage_dict.get(content_id)
            if origin:
                await origin.update(stage.output, set())
            stage.update = detached_update
            stage.detach = detached_detach

        async def detached_update(symbols: set[str]):
            raise DomainError("이미 `detach`되었다.")

        async def detached_detach():
            raise DomainError("이미 `detach`되었다.")

        stage.update = update
        stage.detach = detach
        return stage

    def _define_origin_dep_stage(self, req: BaseReqModel):
        id = self._generate_id(req)
        content_id = req.get_tr_content_id()
        if origin_stage := self._origin_stage_dict.get(content_id):
            return origin_stage
        model_id = get_model_id(req)
        bind_pack = self._get_bind_pack(model_id)
        ctx = bind_pack.get_init_cb()(req)
        stage = OriginStage(
            _STAGE_CREATION_KEY,
            id=id,
            request=req,
        )
        shared_sender = stage.output
        gen: AsyncGenerator[DataModel] | None = None
        transq = TransmitQueue[DataModel]()
        update_lock = Lock()
        active_symbols: set[str] | None = None

        if not isinstance(req, DependentModel):
            raise StageError(f"'DependentModel'이어야 한다. - {get_model_id(req)}")
        binded_cb = bind_pack.get_dependent_cb(req)
        if binded_cb is None:
            raise StageError(f"'dependent_cb'가 'bind'되지 않았다. - {get_model_id(req)}")

        async def update(sender: Sender, symbols: set[str]):
            nonlocal active_symbols, gen
            async with update_lock:
                shared_sender.set_sender(sender, symbols)
                current_symbols = shared_sender.symbols
                if current_symbols == active_symbols:
                    return
                # 상위에 등록하는 심볼도 이 스테이지의 합집합이어야 한다. 이번
                # update의 symbols만 넘기면 같은 transq의 이전 등록을 덮어써
                # 먼저 구독한 쪽이 상위에서 사라진다.
                require, req_symbols = req.get_tr_require_with_symbol(current_symbols)
                if gen:
                    await self._cancel_by_name(id)
                    await gen.aclose()
                    gen = None
                # 업데이트 심볼이 없다면 자원 정리한다.
                if not current_symbols:
                    await self._ensure_require_stage(require, transq, set())
                    self._origin_stage_dict.pop(content_id, None)
                    if bind_pack._detach_cb:
                        await bind_pack._detach_cb(ctx)
                    active_symbols = current_symbols
                    return
                await self._ensure_require_stage(require, transq, req_symbols)
                symbol_set = set(current_symbols)
                gen = binded_cb(ctx, symbol_set, transq.recv)

                async def _(gen: AsyncGenerator[DataModel]):
                    async for data in gen:
                        await shared_sender(data)

                await self._submit(_(gen), id)
                active_symbols = current_symbols

        stage.update = update
        self._origin_stage_dict[content_id] = stage
        return stage

    def _define_inst_stage(self, req: BaseReqModel, output: Sender):
        id = self._generate_id(req)
        stage = Stage(
            _STAGE_CREATION_KEY,
            id=id,
            request=req,
            output=output,
        )
        model_id = get_model_id(req)
        bind_pack = self._get_bind_pack(model_id)
        bind_cb = bind_pack.get_bind_cb()
        unbind_cb = bind_pack.get_unbind_cb()
        detach_cb = bind_pack.get_detach_cb()
        req_cb = bind_pack.get_require_cb()
        if bind_cb is None:
            raise DomainError(f"`@bind`는 바인드 되어야 한다. - {model_id}")
        ctx = bind_pack.get_init_cb()(req)
        transq_dict: dict[str, TransmitQueue[tuple[DataModel, Sequence]]] = {}
        seq_sender_dict: dict[str, set[SequenceSender]] = {}
        router_set: SendRouterSet = SendRouterSet()
        active_stage_set: set[Stage] = set()
        update_lock = Lock()

        async def unbind_symbols(target: set[str]) -> None:
            """슬롯을 닫고 심볼별 정리 콜백을 부른다. `update()`와 `detach()`가 함께 쓴다.

            `bind_cb`로 연 심볼은 어느 경로로 닫히든 `unbind_cb` 한 번으로 짝을 맞춘다.
            """

            if not target:
                return
            for s in target:
                transq_dict.pop(s).shutdown()
                seq_sender_dict.pop(s)
            if unbind_cb:
                async with TaskGroup() as tg:
                    for s in target:
                        tg.create_task(unbind_cb(ctx, s))

        async def update(symbols: set[str]):
            nonlocal req_cb, active_stage_set
            async with update_lock:
                active_symbols: set[str] = set(transq_dict.keys())
                current_symbols: set[str] = symbols | {"__require__"}
                await unbind_symbols(active_symbols - current_symbols)
                if req_cb:
                    transq = TransmitQueue[tuple[DataModel, Sequence]]()
                    transq_dict["__require__"] = transq
                    seq_sender_set: set[SequenceSender] = set()
                    async for seq in req_cb(ctx):
                        seq_sender_set.add(SequenceSender(transq, seq))
                    seq_sender_dict["__require__"] = seq_sender_set
                    await self._submit(
                        self._task_sequence(
                            transq.recv,
                            output,
                        ),
                        f"{id}:__require__",
                    )
                    req_cb = None
                # `current_symbols`는 센티널을 지우지 않으려고 만든 것이라 여기에
                # 쓰면 안 된다. `"__require__"` 슬롯은 위 `req_cb` 분기만 만든다.
                new_symbols = symbols - active_symbols
                if new_symbols:
                    for symbol in new_symbols:
                        transq = TransmitQueue[tuple[DataModel, Sequence]]()
                        transq_dict[symbol] = transq
                        seq_sender_set: set[SequenceSender] = set()
                        async for seq in bind_cb(ctx, symbol):
                            seq_sender_set.add(SequenceSender(transq, seq))
                        seq_sender_dict[symbol] = seq_sender_set
                        await self._submit(
                            self._task_sequence(
                                transq.recv,
                                output,
                            ),
                            f"{id}:{symbol}",
                        )
                router_set.clear()
                for sss in seq_sender_dict.values():
                    for ss in sss:
                        router_set.add_sender(ss.sequence.require, ss)
                current_stage_set: set[Stage] = set()
                updating: list[tuple[Stage, set[str]]] = []
                for reg in router_set():
                    req_stage: Stage | None = None
                    for act in active_stage_set:
                        if act.req_model.get_tr_content_id() == reg.require.get_tr_content_id():
                            if act.output != reg.router:
                                raise DomainError(
                                    "불변 조건의 오류: 두 `Sender`는 같은 객체여야 한다."
                                )
                            req_stage = act
                            break
                    if req_stage is None:
                        req_stage = self._define_stage(reg.require, reg.router)
                    current_stage_set.add(req_stage)
                    # 상위에 등록할 심볼은 시퀀스가 요구한 상위 표기(`seq.symbol`)다.
                    # 이 스테이지가 받은 하위 심볼이 아니다.
                    updating.append((req_stage, reg.router.symbols))
                detaching_stage_set = active_stage_set - current_stage_set
                async with TaskGroup() as tg:
                    for detaching in detaching_stage_set:
                        tg.create_task(detaching.detach())
                async with TaskGroup() as tg:
                    for req_stage, req_symbols in updating:
                        tg.create_task(req_stage.update(req_symbols))
                active_stage_set = current_stage_set

        async def detach():
            # `bind_cb`로 연 슬롯은 모두 짝을 맞춰 닫는다. `"__require__"`는 `req_cb`가
            # 만든 슬롯이라 bind된 적이 없으므로 제외한다.
            await unbind_symbols(set(transq_dict) - {"__require__"})
            for tq in transq_dict.values():  # 남은 것은 `"__require__"` 슬롯뿐이다
                tq.shutdown()
            transq_dict.clear()
            seq_sender_dict.clear()
            async with TaskGroup() as tg:
                for req_stage in active_stage_set:
                    tg.create_task(req_stage.detach())
            if detach_cb:
                await detach_cb(ctx)
            stage.update = detached_update
            stage.detach = detached_detach

        async def detached_update(symbols: set[str]):
            raise DomainError("이미 `detach`되었다.")

        async def detached_detach():
            raise DomainError("이미 `detach`되었다.")

        stage.update = update
        stage.detach = detach
        return stage

    def _define_stage(self, req: BaseReqModel, output: Sender):
        if is_generate_model(req):
            return self._define_gen_stage(req, output)
        if is_dependent_model(req):
            return self._define_dep_stage(req, output)
        if is_instant_model(req):
            return self._define_inst_stage(req, output)
        raise DomainError(
            f"지원 되는 `RequestModel`이 아니거나 등록된 `Model`이 아니다. - {get_model_type(req)}"
        )

    async def _task_sequence(
        self, recv: Receiver[tuple[DataModel, Sequence]], sender: Sender[DataModel]
    ):
        while True:
            try:
                data, seq = await recv()
            except ClosedConnection:
                break
            out_data = await seq.invoke(data)
            if out_data:
                if not out_data.get_tr_req_content_id():
                    out_data._tr_req_content_id = seq.require.get_tr_content_id()
                await sender(out_data)

    async def _gen_req(self, req: BaseReqModel, symbols: set[str]):
        q = TransmitQueue()
        async with self.stage(req, q) as stage:
            await stage.update(symbols)
            while True:
                yield await q.recv()

    async def _submit(self, coro: Coroutine[Any, Any, None], name: str):
        return await self._tmg.submit(coro, name)

    async def _cancel_by_name(self, name: str) -> bool:
        return await self._tmg.cancel_by_name(name)

    async def _close_stage(self, stage: Stage):
        content_id = stage.req_model.get_tr_content_id()
        origin = self._origin_stage_dict.get(content_id)
        if origin:
            await origin.update(stage.output, set())

    def _generate_id(self, req: BaseReqModel):
        self._count += 1
        return f"{get_model_id(req)}:{self._count}"

    def _get_bind_pack(self, model_id: str) -> BindPack:
        bind_pack = BindPack.get_binder(model_id)
        if bind_pack is None:
            raise DomainError(f"요청한 'RequestModel'의 'Binder'를 찾을 수 없다. - {model_id}")
        return bind_pack
