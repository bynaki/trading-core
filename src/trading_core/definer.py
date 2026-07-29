from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import (
    Any,
)

from .exceptions import DefineError
from .model import (
    DataModel,
    Receiver,
    RequestModel,
    Runnable,
    Sequence,
    get_model_id,
)

# P = ParamSpec("P")


class TaskDefiner[**P, T]:
    # def __init__(self, init_cb: Callable[P, T], context_t: type[T]) -> None:
    def __init__(self, init_cb: Callable[P, T]) -> None:
        self._init_cb = init_cb
        self.task_dict: dict[
            str, Callable[[T, DataModel], Coroutine[Any, Any, DataModel | None]]
        ] = {}

    def on[Tget: DataModel](
        self, t_get: type[Tget]
    ) -> Callable[
        [Callable[[T, Tget], Coroutine[Any, Any, DataModel | None]]],
        Callable[[T, Tget], Coroutine[Any, Any, DataModel | None]],
    ]:
        def _(
            cb: Callable[[T, Tget], Coroutine[Any, Any, DataModel | None]],
        ) -> Callable[[T, Tget], Coroutine[Any, Any, DataModel | None]]:
            self.task_dict[get_model_id(t_get)] = cb  # type: ignore
            return cb

        return _

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> TaskRunnable:
        return TaskRunnable(self, args, kwargs)

    async def invoke(self, ctx: T, input: DataModel) -> DataModel | None:
        if cb := self.task_dict.get(get_model_id(input)):
            return await cb(ctx, input)
        else:
            print("warning: input 데이터를 invoke할 callback이 없다.")
            return None


class TaskRunnable(Runnable):
    def __init__(
        self,
        task: TaskDefiner[Any, Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ):
        self._task = task
        self._args = args
        self._kwargs = kwargs or {}
        self._ctx: Any = None

    async def invoke(self, input: DataModel) -> DataModel | None:
        if not self._ctx:
            self._ctx = self._task._init_cb(*self._args, **self._kwargs)  # type: ignore
            assert self._ctx, "Unthinkable!!"
        return await self._task.invoke(self._ctx, input)


def task[**P, T](context_t: type[T]) -> Callable[[Callable[P, T]], TaskDefiner[P, T]]:
    def _(init_cb: Callable[P, T]) -> TaskDefiner[P, T]:
        return TaskDefiner(init_cb)

    return _


# class GeneratorDefiner[Treq: RequestModel]:
#     _definer_dict: dict[str, GeneratorDefiner[Any]] = {}

#     def __init__(
#         self, generator: Callable[[Treq, set[str]], AsyncIterator[DataModel]], req_t: type[Treq]
#     ) -> None:
#         self._generator = generator
#         model_id = get_model_id(req_t)
#         self._definer_dict[model_id] = self

#     @classmethod
#     def get_definer(cls, model_id: str):
#         return cls._definer_dict.get(model_id)

#     def get_binder(self, req: Treq):
#         generator = self._generator

#         def _(symbols: set[str]):
#             return generator(req, symbols)

#         return _


class GeneratorDefiner[Treq: RequestModel, Tctx]:
    _definer_dict: dict[str, GeneratorDefiner[Any, Any]] = {}

    def __init__(self, init_ctx: Callable[[Treq], Tctx], req_t: type[Treq]) -> None:
        self._init_ctx = init_ctx
        self._binder: (
            Callable[[Tctx, set[str], Receiver | None], AsyncGenerator[DataModel]] | None
        ) = None
        self._closer: Callable[[Tctx], Coroutine[Any, Any, None]] | None = None
        model_id = get_model_id(req_t)
        self._definer_dict[model_id] = self

    def __call__(self, req: Treq):
        return self._init_ctx(req)

    def bind(
        self, binder: Callable[[Tctx, set[str], Receiver | None], AsyncGenerator[DataModel]]
    ) -> Callable[[Tctx, set[str], Receiver | None], AsyncGenerator[DataModel]]:
        self._binder = binder
        return binder

    def close(
        self, closer: Callable[[Tctx], Coroutine[Any, Any, None]]
    ) -> Callable[[Tctx], Coroutine[Any, Any, None]]:
        self._closer = closer
        return closer

    @classmethod
    def get_definer(cls, model_id: str):
        return cls._definer_dict.get(model_id)

    def get_binder(self, ctx: Tctx, symbols: set[str], recv: Receiver | None):
        binder = self._binder
        if binder is None:
            return None

        def _():
            return binder(ctx, symbols, recv)

        return _

    def get_closer(self, ctx: Tctx):
        closer = self._closer
        if closer is None:
            return None

        def _():
            return closer(ctx)

        return _


class ProcessorDefiner[Treq: RequestModel, Tctx]:
    _definer_dict: dict[str, ProcessorDefiner[Any, Any]] = {}

    def __init__(self, init_ctx: Callable[[Treq], Tctx], req_t: type[Treq]) -> None:
        self._init_ctx = init_ctx
        self._binder: Callable[[Tctx, str], AsyncGenerator[Sequence[Treq]]] | None = None
        model_id = get_model_id(req_t)
        # if self._processor_dict.get(model_id):
        #     raise DefineError(f"같은 'RequestModel' 이미 등록되어 있다 - ({model_id})")
        self._definer_dict[model_id] = self

    def __call__(self, req: Treq):
        return self._init_ctx(req)

    def bind(
        self, binder: Callable[[Tctx, str], AsyncGenerator[Sequence[Treq]]]
    ) -> Callable[[Tctx, str], AsyncGenerator[Sequence[Treq]]]:
        self._binder = binder
        return binder

    # def generator(
    #     self, cb: Callable[[Tctx, set[str]], AsyncIterator[DataModel]]
    # ) -> Callable[[Tctx, set[str]], AsyncIterator[DataModel]]:
    #     self._gen_cb = cb
    #     return cb

    @classmethod
    def get_definer(cls, model_id: str):
        return cls._definer_dict.get(model_id)

    def get_binder(self, ctx: Tctx):
        if self._binder is None:
            return None
        binder = self._binder

        def _(symbol: str):
            return binder(ctx, symbol)

        return _


# class StageContext[Treq: RequestModel]:
#     def __init__(self, req: Treq) -> None:
#         self.req_model = req


def processor[Treq: RequestModel, Tctx](
    request_t: type[Treq],
) -> Callable[[Callable[[Treq], Tctx]], ProcessorDefiner[Treq, Tctx]]:
    if request_t._tr_model_type != "unregistered":
        raise DefineError(f"같은 'RequestModel' 이미 등록되어 있다 - ({get_model_id(request_t)})")
    request_t._tr_model_type = "processor"

    def _(init_cb: Callable[[Treq], Tctx]) -> ProcessorDefiner[Treq, Tctx]:
        return ProcessorDefiner(init_cb, request_t)

    return _


def generator[Treq: RequestModel, Tctx](
    request_t: type[Treq],
) -> Callable[[Callable[[Treq], Tctx]], GeneratorDefiner[Treq, Tctx]]:
    if request_t._tr_model_type != "unregistered":
        raise DefineError(f"같은 'RequestModel' 이미 등록되어 있다 - ({get_model_id(request_t)})")
    request_t._tr_model_type = "generator"

    def _(init_cb: Callable[[Treq], Tctx]) -> GeneratorDefiner[Treq, Tctx]:
        return GeneratorDefiner(init_cb, request_t)

    return _


# def generator[Treq: RequestModel](
#     request_t: type[Treq],
# ) -> Callable[
#     [Callable[[Treq, set[str]], AsyncIterator[DataModel]]],
#     # Callable[[Treq, set[str]], AsyncIterator[DataModel]],
#     GeneratorDefiner[Treq],
# ]:
#     if request_t._tr_model_type != "unregistered":
#         raise DefineError(f"같은 'RequestModel' 이미 등록되어 있다 - ({get_model_id(request_t)})")
#     request_t._tr_model_type = "generator"

#     def _(cb: Callable[[Treq, set[str]], AsyncIterator[DataModel]]):
#         return GeneratorDefiner(cb, request_t)

#     return _
