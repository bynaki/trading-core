from asyncio import Queue, TaskGroup
from collections.abc import AsyncGenerator, Coroutine
from contextlib import aclosing, asynccontextmanager
from typing import Any, NotRequired, TypedDict, Unpack

from .definer import GeneratorDefiner
from .exceptions import StageError
from .helper import TaskManager
from .model import (
    DataModel,
    RequestModel,
    Runnable,
    Sender,
    get_model_id,
    get_model_type,
)


class DomainError(Exception): ...


# from .definer import StageDefiner

# from .model import RequestModel, get_model_id, DataModel, get_model_type
# from typing import Protocol


# class StageError(Exception): ...


# class StageProtocol[T: RequestModel](Protocol):
#     def __init__(self, req: T): ...
#     async def update(self, symbols: set[str]) -> None: ...
#     async def relay(self) -> DataModel: ...


# class Stage[T: RequestModel]:
#     def __init__(self, domain: Domain, req: T):
#         self._domain = domain
#         req_id = get_model_id(req)
#         if definer := StageDefiner.get_definer(req_id):
#             ...
#         else:
#             raise StageError(f"현재 요청한 'Request'는 정의되지 않았다. - {req}")
#         self._definer = definer
#         self._req = req
#         if ctx := definer(req):
#             ...
#         else:
#             ctx = req
#         self._ctx = ctx

#     async def update(self, symbols: set[str]):
#         if update_cb := self._definer.get_update_callback(self._ctx):
#             transmitter = await update_cb(symbols)


#     # async def update(self, symbols: set[str]):
#     #     for symbol in symbols:
#     #         cb = self._definer._on_cb  # type: ignore
#     #         async for sequence in cb(self._ctx, symbol):
#     #             steps = sequence._steps  # type: ignore
#     #             for step in steps:
#     #                 sequence.req_model

#     async def get(self) -> DataModel:
#         ...


# class Domain:
#     def __init__(self) -> None:
#         self._stage_set: set[Stage[RequestModel]] = set()

#     async def stage(self, req: RequestModel, symbols: list[str]):
#         for stage in self._stage_set:
#             ttype = get_model_type(req)
#             if ttype == "require":

#             req.get_tr_content_id(exclude={"symbols"})


class ClosedConnection(Exception): ...


# class Node2[T: RequestModel]:
#     def __init__(self, request: T, symbols: set[Sequence]) -> None:
#         self._req = request
#         self._sequence_dict: dict[str, set[Sequence[T]]] = {}


# class Node[Treq: RequestModel]:
#     def __init__(self, seq: Sequence[Treq]) -> None:
#         self._seq = seq
#         self._joins: set[Node] = set()

#     @property
#     def require(self) -> Treq:
#         return self._seq.require

#     @property
#     def symbol(self) -> str:
#         return self._seq.symbol

#     async def invoke(self, input: DataModel) -> None:
#         data = await self._seq.invoke(input)
#         if not data:
#             return
#         if not self._joins:
#             raise NodeError("'Join'할게 없으면 아웃풋 데이터는 'None'이어야 한다.")
#         joins = list(self._joins)
#         results: list[None | BaseException] = await gather(
#             *[s.invoke(data) for s in joins], return_exceptions=True
#         )
#         errors: list[Exception] = []
#         removing: set[Node] = set()
#         for i, error in enumerate(results):
#             if isinstance(error, ExceptionGroup):
#                 # group = cast(ExceptionGroup[Exception], error)
#                 errors.extend(error.exceptions)
#             elif isinstance(error, Exception):
#                 errors.append(error)
#             removing.add(joins[i])
#         self._joins -= removing
#         if not self._joins:
#             errors.append(NodeError("더이상 'Join'할게 없다."))
#         if errors:
#             raise ExceptionGroup("Sequence Error!!", errors)


# class Require(Runnable):
#     def __init__(self, req: RequestModel, symbols: set[str]) -> None:
#         self.request = req
#         self.symbols = symbols

#     def set_edge(self, edge: Edge):
#         self._edge = edge


class Segment:
    def __init__(self, req: RequestModel, symbols: set[str]):
        self._req = req
        self._symbols = symbols

    @property
    def request(self) -> RequestModel:
        return self._req

    @property
    def symbols(self) -> set[str]:
        return self._symbols


class Edge(Runnable):
    def __init__(self): ...

    async def invoke(self, input: DataModel) -> None: ...

    def add_segment(self, req: RequestModel, symbols: set[str]): ...

    def get_segment_set(self) -> set[Segment]: ...


class TransmitQueue(Sender):
    def __init__(self):
        self._q = Queue[DataModel]()

    async def send(self, data: DataModel) -> None:
        return await self._q.put(data)

    async def __call__(self, data: DataModel) -> None:
        return await self.send(data)

    async def recv(self) -> DataModel:
        return await self._q.get()

    async def close(self) -> None:
        self._q.shutdown()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


class SharedSender:
    def __init__(self):
        self._senders: set[tuple[Sender, frozenset[str]]] = set()

    def set_sender(self, sender: Sender, symbols: set[str]):
        for st in self._senders:
            if st[0] == sender:
                self._senders.remove(st)
                break
        self._senders.add((sender, frozenset(symbols)))

    @property
    def symbols(self):
        syms: set[str] = set()
        for st in self._senders:
            syms.update(st[1])
        return syms

    async def __call__(self, data: DataModel) -> None:
        async with TaskGroup() as tg:
            for st in self._senders:
                if data.symbol in st[1]:
                    tg.create_task(st[0](data))


class StageParam[Treq: RequestModel, Tput: Sender](TypedDict):
    id: str
    request: Treq
    output: Tput
    definer: NotRequired[GeneratorDefiner]
    context: NotRequired[Any]


class Stage[Treq: RequestModel, Tput: Sender]:
    def __init__(self, **params: Unpack[StageParam]) -> None:
        self._params = params

    @property
    def id(self) -> str:
        return self._params["id"]

    @property
    def req_model(self) -> Treq:
        return self._params["request"]

    @property
    def output(self) -> Tput:
        return self._params["output"]

    @property
    def definer(self) -> GeneratorDefiner | None:
        return self._params.get("definer")

    @property
    def context(self) -> Any:
        return self._params.get("context")

    async def update(self, symbols: set[str]) -> None: ...


# class Stage[Treq: RequestModel, Tput: Sender](Protocol):
#     _domain: Domain
#     _req: Treq
#     _output: Tput
#     _id: str

#     def __init__(self, domain: Domain, req: Treq, output: Tput) -> None:
#         self._domain = domain
#         self._req = req
#         self._output = output
#         self._id = domain.generate_id(req)

#     def get_domain(self) -> Domain:
#         return self._domain

#     @property
#     def id(self) -> str:
#         return self._id

#     @property
#     def req_model(self) -> Treq:
#         return self._req

#     @property
#     def output(self) -> Tput:
#         return self._output

#     async def update(self, symbols: set[str]) -> None: ...


# class GeneratorOriginStage[Treq: RequestModel, Tput: Sender](Stage[Treq, Tput]):
#     def __init__(self, domain: Domain, req: Treq, output: Tput) -> None:
#         super().__init__(domain, req, output)
#         self._model_id = get_model_id(req)
#         self._ctx = self._get_definer()

#     def _get_definer(self) -> GeneratorDefiner:
#         definer = GeneratorDefiner.get_definer(self._model_id)
#         if definer is None:
#             raise StageError(
#                 f"요청한 'RequestModel'의 'Definer'를 찾을 수 없다. - {self._model_id}"
#             )
#         return definer

#     async def update(self, symbols: set[str]) -> None:
#         definer = self._get_definer()
#         gen = definer.get_binder(self._ctx, symbols, None)
#         if gen is None:
#             raise StageError("'bind'되지 않았다.")

#         async def _():
#             async for data in gen():
#                 await self._output(data)

#         await self._domain.cancel_by_name(self.id)
#         await self._domain.submit(_(), self.id)


# class GeneratorStage[Treq: RequestModel, Tput: Sender](Stage[Treq, Tput]):
#     def __init__(self, domain: Domain, req: Treq, output: Tput) -> None:
#         super().__init__(domain, req, output)

#     async def update(self, symbols: set[str]) -> None:
#         content_id = self.req_model.get_tr_content_id(exclude={"symbols"})
#         origin = self.get_domain().get_origin_stage(content_id)
#         if origin is None:
#             raise StageError(f"GeneratorOriginStage가 없다. - {content_id}")
#         origin_output: SharedSender = origin.output  # type: ignore
#         origin_output.set_sender(self.output, symbols)
#         await origin.update(origin_output.symbols)


# class ProcessorStage[Treq: RequestModel, Tput: Sender](Stage[Treq, Tput]):
#     def __init__(self, domain: Domain, req: Treq, output: Tput) -> None: ...

#     async def update(self, symbols: set[str]) -> None: ...


class Domain:
    def __init__(self) -> None:
        self._tmg = TaskManager()
        self._origin_stage_dict: dict[str, Stage] = {}
        self._count = 0

    def get_origin_stage(self, content_id: str):
        return self._origin_stage_dict.get(content_id)

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
        stage: Stage[RequestModel, SharedSender] = self._define_origin_gen_stage(req)
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
        stage = Stage(
            id=id,
            request=req,
            output=shared_sender,
            definer=definer,
            context=ctx,
        )
        gen: AsyncGenerator[DataModel] | None = None
        transq = TransmitQueue()

        async def update(symbols: set[str]):
            require = req.tr_require
            if require:
                await self._ensure_require_stage(require, transq, symbols)
                bind = definer.get_binder(ctx, symbols, transq.recv)
            else:
                bind = definer.get_binder(ctx, symbols, None)
            if bind is None:
                raise StageError("'bind'되지 않았다.")
            nonlocal gen
            if gen:
                await gen.aclose()
            gen = bind()

            async def _(gen: AsyncGenerator[DataModel]):
                async for data in gen:
                    await shared_sender(data)

            await self._submit(_(gen), id)

        stage.update = update
        self._origin_stage_dict[content_id] = stage
        return stage

    def _define_gen_stage(self, req: RequestModel, output: Sender):
        stage = Stage(
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
            while True:
                yield await q.recv()

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

    async def _close_stage(self, stage: Stage[RequestModel, Sender]): ...

    def _generate_id(self, req: RequestModel):
        self._count += 1
        return f"{get_model_id(req)}:{self._count}"

    def _get_gen_definer(self, model_id: str) -> GeneratorDefiner:
        definer = GeneratorDefiner.get_definer(model_id)
        if definer is None:
            raise DomainError(f"요청한 'RequestModel'의 'Definer'를 찾을 수 없다. - {model_id}")
        return definer


async def main():
    domain = Domain()
    async with domain.request(RequestModel(), {"B"}) as gen:
        async for data in gen:
            print(data)
