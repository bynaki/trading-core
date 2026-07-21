from asyncio import Lock, Queue, QueueShutDown, TaskGroup
from collections.abc import AsyncGenerator, Coroutine
from contextlib import aclosing, asynccontextmanager
from typing import Any, TypedDict, Unpack

from .definer import GeneratorDefiner
from .exceptions import DomainError, StageError
from .helper import TaskManager
from .model import (
    DataModel,
    RequestModel,
    Sender,
    get_model_id,
    get_model_type,
)


class ClosedConnection(Exception): ...


class TransmitQueue(Sender):
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

    async def close(self) -> None:
        self._q.shutdown()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


class SharedSender(Sender):
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
    def symbols(self):
        syms: set[str] = set()
        for st in self._senders:
            syms.update(st[1])
        return syms

    async def __call__(self, data: DataModel) -> None:
        sent = False
        async with TaskGroup() as tg:
            for st in self._senders:
                if data.symbol in st[1]:
                    tg.create_task(st[0](data))
                    sent = True
        if not sent:
            print("warning: 데이터을 전송할 'Sender'가 없다.")

    async def close(self) -> None:
        try:
            async with TaskGroup() as tg:
                for st in self._senders:
                    tg.create_task(st[0].close())
        finally:
            self._senders.clear()


class _StageCreationKey:
    pass


_STAGE_CREATION_KEY = _StageCreationKey()


class Stage[Tout: Sender]:
    def __init__(
        self,
        key: _StageCreationKey,
        /,
        id: str,
        request: RequestModel,
        output: Tout,
    ) -> None:
        if key is not _STAGE_CREATION_KEY:
            raise TypeError("'Stage'는 'Domain'을 통해서만 생성할 수 있다.")
        self._id = id
        self._req_model = request
        self._output = output

    @property
    def id(self) -> str:
        return self._id

    @property
    def req_model(self) -> RequestModel:
        return self._req_model

    @property
    def output(self) -> Tout:
        return self._output

    # @property
    # def definer(self) -> GeneratorDefiner | None:
    #     return self._params.get("definer")

    # @property
    # def context(self) -> Any:
    #     return self._params.get("context")

    async def update(self, symbols: set[str]) -> None:
        raise StageError("'update()'가 구현되지 않았다.")


class StageParam[Tout: Sender](TypedDict):
    id: str
    request: RequestModel
    output: Tout
    definer: GeneratorDefiner
    context: Any


class OriginGenStage(Stage[SharedSender]):
    def __init__(
        self,
        key: _StageCreationKey,
        /,
        **params: Unpack[StageParam[SharedSender]],
    ) -> None:
        super().__init__(key, params["id"], params["request"], params["output"])
        self._definer = params["definer"]
        self._context = params["context"]

    @property
    def definer(self) -> GeneratorDefiner[RequestModel, Any] | None:
        return self._definer

    @property
    def context(self) -> Any:
        return self._context


class Domain:
    def __init__(self) -> None:
        self._tmg = TaskManager()
        self._origin_stage_dict: dict[str, OriginGenStage] = {}
        self._count = 0

    @asynccontextmanager
    async def stage(self, req: RequestModel, output: Sender):
        if get_model_type(req) == "generator":
            stage = self._define_gen_stage(req, output)
        else:
            # TODO:
            stage = self._define_gen_stage(req, output)
        try:
            yield stage
        finally:
            await self._close_stage(stage)

    async def _ensure_require_stage(
        self, req: RequestModel, transq: TransmitQueue, symbols: set[str]
    ):
        content_id = req.get_tr_content_id()
        stage = self._origin_stage_dict.get(content_id)
        if stage is None:
            if not symbols:
                return
            stage = self._define_origin_gen_stage(req)
        output = stage.output
        output.set_sender(transq, symbols)
        await stage.update(output.symbols)

    def _define_origin_gen_stage(self, req: RequestModel):
        id = self._generate_id(req)
        content_id = req.get_tr_content_id(exclude={"symbols"})
        if origin_stage := self._origin_stage_dict.get(content_id):
            return origin_stage
        shared_sender = SharedSender()
        model_id = get_model_id(req)
        definer = self._get_gen_definer(model_id)
        ctx = definer(req)
        stage = OriginGenStage(
            _STAGE_CREATION_KEY,
            id=id,
            request=req,
            output=shared_sender,
            definer=definer,
            context=ctx,
        )
        gen: AsyncGenerator[DataModel] | None = None
        transq = TransmitQueue()
        update_lock = Lock()
        active_symbols: frozenset[str] | None = None
        completed = False

        async def update(symbols: set[str]):
            nonlocal active_symbols, gen
            async with update_lock:
                current_symbols = frozenset(shared_sender.symbols)
                if current_symbols == active_symbols:
                    return
                print(f"update({set(current_symbols)} - {id})")
                if gen and not completed:
                    await self._cancel_by_name(id)
                    await gen.aclose()
                    gen = None
                require = req.tr_require
                # 업데이트 심볼이 없다면 자원 정리한다.
                if not current_symbols:
                    if require:
                        await self._ensure_require_stage(require, transq, set())
                    self._origin_stage_dict.pop(content_id, None)
                    closer = definer.get_closer(ctx)
                    if closer:
                        await closer()
                    active_symbols = current_symbols
                    return
                if completed:
                    active_symbols = current_symbols
                    return
                #
                symbol_set = set(current_symbols)
                if require:
                    await self._ensure_require_stage(require, transq, symbol_set)
                    bind = definer.get_binder(ctx, symbol_set, transq.recv)
                else:
                    bind = definer.get_binder(ctx, symbol_set, None)
                if bind is None:
                    raise StageError("'bind'되지 않았다.")
                gen = bind()

                async def _(gen: AsyncGenerator[DataModel]):
                    nonlocal completed
                    async for data in gen:
                        await shared_sender(data)
                    completed = True
                    await shared_sender.close()

                print(f"submit({id}) && content_id: {content_id}")
                await self._submit(_(gen), id)
                active_symbols = current_symbols

        stage.update = update
        self._origin_stage_dict[content_id] = stage
        return stage

    def _define_gen_stage(self, req: RequestModel, output: Sender):
        stage = Stage(
            _STAGE_CREATION_KEY,
            id=self._generate_id(req),
            request=req,
            output=output,
        )

        async def update(symbols: set[str]):
            origin_stage = self._define_origin_gen_stage(req)
            shared = origin_stage.output
            shared.set_sender(output, symbols)
            shared_symbols = shared.symbols
            await origin_stage.update(shared_symbols)

        stage.update = update
        return stage

    def request(self, req: RequestModel, symbols: set[str]):
        return aclosing(self._gen_req(req, symbols))

    async def _gen_req(self, req: RequestModel, symbols: set[str]):
        q = TransmitQueue()
        async with self.stage(req, q) as stage:
            await stage.update(symbols)
            try:
                while True:
                    yield await q.recv()
            except ClosedConnection:
                ...

    async def start(self):
        return await self._tmg.start()

    async def wait(self):
        return await self._tmg.wait()

    async def stop(self):
        return await self._tmg.stop()

    async def _submit(self, coro: Coroutine[Any, Any, None], name: str):
        return await self._tmg.submit(coro, name)

    async def _cancel_by_name(self, name: str) -> bool:
        return await self._tmg.cancel_by_name(name)

    async def _close_stage(self, stage: Stage[Sender]):
        content_id = stage.req_model.get_tr_content_id(exclude={"symbols"})
        origin = self._origin_stage_dict.get(content_id)
        if origin:
            shared_sender = origin.output
            shared_sender.set_sender(stage.output, set())
            await origin.update(shared_sender.symbols)

    def _generate_id(self, req: RequestModel):
        self._count += 1
        return f"{get_model_id(req)}:{self._count}"

    def _get_gen_definer(self, model_id: str) -> GeneratorDefiner:
        definer = GeneratorDefiner.get_definer(model_id)
        if definer is None:
            raise DomainError(f"요청한 'RequestModel'의 'Definer'를 찾을 수 없다. - {model_id}")
        return definer
