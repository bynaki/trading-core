from .model import (
    Runnable,
    DataModel,
    RequestModel,
    get_model_id,
    Sequence,
)
from typing import (
    Any,
    ParamSpec,
    TypeVar,
    Generic,
    Coroutine,
    Self,
)
from collections.abc import Callable, AsyncIterator


P = ParamSpec("P")
T = TypeVar("T")
Treq = TypeVar("Treq", bound="RequestModel")
Tget = TypeVar("Tget", bound="DataModel")
Tput = TypeVar("Tput", bound="DataModel")


class TaskModel(Generic[P, T]):
    # def __init__(self, init_cb: Callable[P, T], context_t: type[T]) -> None:
    def __init__(self, init_cb: Callable[P, T]) -> None:
        self._init_cb = init_cb
        self.task_dict: dict[str, Callable[[T, DataModel], Coroutine[Any, Any, DataModel | None]]] = {}

    def on(self, t_get: type[Tget]):
        def _(cb: Callable[[T, Tget], Coroutine[Any, Any, DataModel | None]]):
            self.task_dict[get_model_id(t_get)] = cb  # type: ignore
            return cb
        return _

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> TaskRunnable:
        return TaskRunnable(self, args, kwargs)

    async def invoke(self, ctx: T, input: DataModel):
        if cb := self.task_dict.get(get_model_id(input)):
            return await cb(ctx, input)
        else:
            print("warning: input 데이터를 invoke할 callback이 없다.")


class TaskRunnable(Runnable):
    def __init__(
        self,
        task: TaskModel[Any, Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ):
        self._task = task
        self._args = args
        self._kwargs = kwargs or {}
        self._ctx = None

    async def invoke(self, input: DataModel) -> DataModel | None:
        if not self._ctx:
            self._ctx = self._task._init_cb(*self._args, **self._kwargs)  # type: ignore
            assert self._ctx, "Unthinkable!!"
        return await self._task.invoke(self._ctx, input)


def task(context_t: type[T]):
    def _(init_cb: Callable[P, T]) -> TaskModel[P, T]:
        return TaskModel(init_cb)
    return _


class DomainError(Exception): ...


class DomainModel(Generic[Treq, T]):
    _domain_dict: dict[str, Self] = {}

    def __init__(self, init_cb: Callable[[Treq], T], req_t: type[Treq]) -> None:
        self._init_cb = init_cb
        model_id = get_model_id(req_t)
        if self._domain_dict.get(model_id):
            raise DomainError(f"같은 모델이 이미 등록되어 있다 - ({model_id})")
        self._domain_dict[model_id] = self

    # def on(self, cb: Callable[[T, str], AsyncGenerator[Sequence[Treq], Any]]):
    def on(
        self, cb: Callable[[T, str], AsyncIterator[Sequence[Treq]]]
    ) -> Callable[[T, str], AsyncIterator[Sequence[Treq]]]:
        self._on_cb = cb
        return cb


class DomainContext(Generic[Treq]):
    def __init__(self, req: Treq) -> None:
        self.req_model = req


def domain(request_t: type[Treq], context_t: type[T] = DomainContext[Treq]):
    def _(init_cb: Callable[[Treq], T]) -> DomainModel[Treq, T]:
        return DomainModel[Treq, T](init_cb, request_t)
    return _

