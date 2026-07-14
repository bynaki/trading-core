from asyncio import Queue, TaskGroup
from collections.abc import AsyncGenerator, Coroutine
from contextlib import aclosing, asynccontextmanager
from typing import Any, NotRequired, TypedDict, Unpack

from .definer import GeneratorDefiner
from .exceptions import DomainError, StageError
from .helper import TaskManager
from .model import (
    DataModel,
    RequestModel,
    Runnable,
    Sender,
    get_model_id,
    get_model_type,
)


class ClosedConnection(Exception): ...


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

    async def update(self, symbols: set[str]) -> None:
        raise StageError("'update()'가 구현되지 않았다.")


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
