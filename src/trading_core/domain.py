from asyncio import Lock, Queue, QueueShutDown, TaskGroup
from collections.abc import AsyncGenerator, Coroutine
from contextlib import aclosing, asynccontextmanager
from typing import Any, cast

from .binder import (
    BindPack,
)
from .exceptions import DomainError, StageError
from .helper import TaskManager
from .model import (
    BaseReqModel,
    DataModel,
    DependentModel,
    GenerateModel,
    Sender,
    get_model_id,
    get_model_type,
)


class ClosedConnection(Exception): ...


class TransmitQueue:
    def __init__(self):
        self._q = Queue[DataModel]()

    async def send(self, data: DataModel) -> None:
        try:
            return await self._q.put(data)
        except QueueShutDown as exc:
            raise ClosedConnection("'TransmitQueue'가 이미 닫혔다. - send()") from exc

    async def __call__(self, data: DataModel) -> None:
        return await self.send(data)

    async def recv(self) -> DataModel:
        try:
            return await self._q.get()
        except QueueShutDown as exc:
            raise ClosedConnection("'TransmitQueue'가 이미 닫혔다. - recv()") from exc


class SharedSender:
    def __init__(self):
        self._senders: set[tuple[Sender, frozenset[str]]] = set()

    def set_sender(self, sender: Sender, symbols: set[str]):
        for st in self._senders:
            if st[0] == sender:
                self._senders.remove(st)
                break
        if symbols:
            self._senders.add((sender, frozenset(symbols)))

    @property
    def symbols(self) -> set[str]:
        syms: set[str] = set()
        for st in self._senders:
            syms.update(st[1])
        return set(syms)

    async def __call__(self, data: DataModel) -> None:
        sent = False
        async with TaskGroup() as tg:
            for st in self._senders:
                if data.symbol in st[1]:
                    tg.create_task(st[0](data))
                    sent = True
        if not sent:
            print("warning: 데이터을 전송할 'Sender'가 없다.")


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


class OriginGenStage[T: BaseReqModel](BaseStage[T]):
    def __init__(self, key: _StageCreationKey, /, id: str, request: T) -> None:
        super().__init__(key, id, request, SharedSender())

    async def update(self, sender: Sender, symbols: set[str]) -> None:
        raise StageError("'update()'가 구현되지 않았다.")

    @property
    def output(self) -> SharedSender:
        return cast(SharedSender, self._output)


class Domain:
    def __init__(self) -> None:
        self._tmg = TaskManager()
        self._origin_stage_dict: dict[str, OriginGenStage] = {}
        self._count = 0

    @asynccontextmanager
    async def stage(self, req: BaseReqModel, output: Sender):
        if get_model_type(req) == "generator":
            stage = self._define_gen_stage(req, output)
        else:
            # TODO:
            stage = self._define_gen_stage(req, output)
        try:
            yield stage
        finally:
            await self._close_stage(stage)

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
        self, req: BaseReqModel, transq: TransmitQueue, symbols: set[str]
    ):
        content_id = req.get_tr_content_id()
        stage = self._origin_stage_dict.get(content_id)
        if stage is None:
            if not symbols:
                return
            stage = self._define_origin_gen_stage(req)
        await stage.update(transq, symbols)

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

        stage.update = update
        return stage

    def _define_origin_gen_stage(self, req: BaseReqModel):
        id = self._generate_id(req)
        content_id = req.get_tr_content_id()
        if origin_stage := self._origin_stage_dict.get(content_id):
            return origin_stage
        model_id = get_model_id(req)
        bind_pack = self._get_bind_pack(model_id)
        ctx = bind_pack._init_cb(req)
        stage = OriginGenStage(
            _STAGE_CREATION_KEY,
            id=id,
            request=req,
        )
        shared_sender = stage.output
        gen: AsyncGenerator[DataModel] | None = None
        transq = TransmitQueue()
        update_lock = Lock()
        active_symbols: set[str] | None = None

        if get_model_type(req) == "generator":
            if not isinstance(req, GenerateModel):
                raise StageError(f"'GenerateModel'이어야 한다. - {get_model_id(req)}")
            binded_cb = bind_pack.get_generate_cb()
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
        #
        elif get_model_type(req) == "dependent_generator":
            if not isinstance(req, DependentModel):
                raise StageError(f"'DependentModel'이어야 한다. - {get_model_id(req)}")
            binded_cb = bind_pack.get_dependent_cb()
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
        #
        else:
            raise StageError("'origin stage'는 'GenerateModel', 'DependentModel' 만 허락한다.")
        #
        stage.update = update
        self._origin_stage_dict[content_id] = stage
        return stage

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
