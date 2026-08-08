from collections.abc import AsyncGenerator, Callable, Coroutine
from inspect import signature
from typing import Any, Protocol, get_type_hints, overload

from trading_core.exceptions import BindError
from trading_core.model import (
    BaseReqModel,
    DataModel,
    DependentModel,
    GenerateModel,
    Receiver,
    RequestModel,
    Sequence,
    get_model_id,
)

type InitCb[Tctx, Treq: BaseReqModel] = Callable[[Treq], Tctx]
type GenerateCb[Tctx] = Callable[[Tctx, set[str]], AsyncGenerator[DataModel]]
type DependentCb[Tctx] = Callable[[Tctx, set[str], Receiver], AsyncGenerator[DataModel]]
type DetachCb[Tctx] = Callable[[Tctx], Coroutine[Any, Any, None]]
type BindCb[Tctx] = Callable[[Tctx, str], Coroutine[Any, Any, Sequence]]
type UnbindCb[Tctx] = Callable[[Tctx, str], Coroutine[Any, Any, None]]
type RequireCb[Tctx] = Callable[[Tctx], Coroutine[Any, Any, Sequence]]


class BindPack[Tctx, Treq: BaseReqModel]:
    _binder_dict: dict[str, BindPack] = {}

    def __init__(self, request_t: type[Treq], init_cb: InitCb[Tctx, Treq]) -> None:
        model_id = get_model_id(request_t)
        if self._binder_dict.get(model_id):
            raise BindError(f"이미 'binder'가 있다. - {model_id}")
        self._binder_dict[model_id] = self
        self._request_t: type[Treq] = request_t
        self._init_cb: InitCb[Tctx, Treq] = init_cb
        self._generate_cb: GenerateCb[Tctx] | None = None
        self._dependent_cb: DependentCb[Tctx] | None = None
        self._bind_cb_set: set[BindCb[Tctx]] = set()
        self._unbind_cb: UnbindCb[Tctx] | None = None
        self._require_cb_set: set[RequireCb[Tctx]] = set()
        self._detach_cb: DetachCb[Tctx] | None = None

    @classmethod
    def get_binder(cls, model_id: str):
        return cls._binder_dict.get(model_id)

    @property
    def request_t(self) -> type[Treq]:
        return self._request_t

    def set_generate_cb(self, cb: GenerateCb[Tctx]):
        if not issubclass(self._request_t, GenerateModel):
            raise BindError("'GenerateModel'이 아니다.")
        if self._request_t._tr_model_type != "unregistered":
            raise BindError(
                f"같은 'GenerateModel' 이미 등록되어 있다 - ({get_model_id(self._request_t)})"
            )
        self._request_t._tr_model_type = "generator"
        self._generate_cb = cb

    def get_generate_cb(self) -> GenerateCb[Tctx] | None:
        return self._generate_cb

    def set_dependent_cb(self, cb: DependentCb[Tctx]):
        if not issubclass(self._request_t, DependentModel):
            raise BindError(f"'DependentModel'이 아니다. - {get_model_id(self._request_t)}")
        if self._request_t._tr_model_type != "unregistered":
            raise BindError(
                f"같은 'DependentModel' 이미 등록되어 있다 - ({get_model_id(self._request_t)})"
            )
        if self._request_t.tr_require is None:
            raise BindError(
                f"'require'가 먼저 바인드 되어야 한다. - {get_model_id(self._request_t)}"
            )
        self._request_t._tr_model_type = "dependent_generator"
        self._dependent_cb = cb

    def get_dependent_cb(self) -> DependentCb[Tctx] | None:
        return self._dependent_cb

    def add_bind_cb(self, cb: BindCb[Tctx]):
        if not issubclass(self._request_t, RequestModel):
            raise BindError(f"'RequestModel'이 아니다. - {get_model_id(self._request_t)}")
        self._request_t._tr_model_type = "request"
        self._bind_cb_set.add(cb)

    def get_bind_cb_set(self) -> set[BindCb[Tctx]]:
        return self._bind_cb_set

    def set_unbind_cb(self, cb: UnbindCb[Tctx]):
        if not issubclass(self._request_t, RequestModel):
            raise BindError(f"'RequestModel'이 아니다. - {get_model_id(self._request_t)}")
        if self._unbind_cb is not None:
            raise BindError(f"'unbind'가 이미 바인드 되었다. - {get_model_id(self._request_t)}")
        self._unbind_cb = cb

    def get_unbind_cb(self) -> UnbindCb[Tctx] | None:
        return self._unbind_cb

    def add_require_cb(self, cb: RequireCb[Tctx]):
        if not issubclass(self._request_t, RequestModel):
            raise BindError(f"'RequestModel'이 아니다. - {get_model_id(self._request_t)}")
        self._request_t._tr_model_type = "request"
        self._require_cb_set.add(cb)

    def get_require_cb_set(self) -> set[RequireCb[Tctx]]:
        return self._require_cb_set

    def set_detach_cb(self, cb: DetachCb[Tctx]):
        self._detach_cb = cb

    def get_detach_cb(self) -> DetachCb[Tctx] | None:
        return self._detach_cb


class BaseBinder[Tctx, Treq: BaseReqModel]:
    def __init__(self, pack: BindPack[Tctx, Treq]):
        self._pack = pack

    def detached(self, cb: DetachCb[Tctx]) -> DetachCb[Tctx]:
        self._pack.set_detach_cb(cb)
        return cb


class GenerateModelBinder[Tctx, Treq: GenerateModel](BaseBinder[Tctx, Treq]):
    def __call__(self, cb: GenerateCb[Tctx]) -> GenerateModelBinder:
        return self.generate(cb)

    def generate(self, cb: GenerateCb[Tctx]):
        self._pack.set_generate_cb(cb)
        return self


class DependentModelBinder[Tctx, Treq: DependentModel](BaseBinder[Tctx, Treq]):
    def __call__(self, cb: DependentCb[Tctx]) -> DependentModelBinder:
        return self.generate(cb)

    def generate(self, cb: DependentCb[Tctx]):
        self._pack.set_dependent_cb(cb)
        return self


class RequestModelBinder[Tctx, Treq: RequestModel](BaseBinder[Tctx, Treq]):
    def __call__(self, cb: BindCb[Tctx]) -> RequestModelBinder:
        return self.bind(cb)

    def bind(self, cb: BindCb[Tctx]) -> RequestModelBinder[Tctx, Treq]:
        self._pack.add_bind_cb(cb)
        return self

    def unbind(self, cb: UnbindCb[Tctx]) -> RequestModelBinder[Tctx, Treq]:
        self._pack.set_unbind_cb(cb)
        return self

    def require(self, cb: RequireCb[Tctx]) -> RequestModelBinder[Tctx, Treq]:
        self._pack.add_require_cb(cb)
        return self


class InitGenWrap[Treq: GenerateModel](Protocol):
    def __call__[Tctx](self, cb: InitCb[Tctx, Treq]) -> GenerateModelBinder[Tctx, Treq]: ...


class InitDependWrap[Treq: DependentModel](Protocol):
    def __call__[Tctx](self, cb: InitCb[Tctx, Treq]) -> DependentModelBinder[Tctx, Treq]: ...


class InitReqWrap[Treq: RequestModel](Protocol):
    def __call__[Tctx](self, cb: InitCb[Tctx, Treq]) -> RequestModelBinder[Tctx, Treq]: ...


@overload
def initialize[Tctx, Treq: GenerateModel](
    cb: InitCb[Tctx, Treq],
) -> GenerateModelBinder[Tctx, Treq]: ...


@overload
def initialize[Tctx, Treq: DependentModel](
    cb: InitCb[Tctx, Treq],
) -> DependentModelBinder[Tctx, Treq]: ...


@overload
def initialize[Tctx, Treq: RequestModel](
    cb: InitCb[Tctx, Treq],
) -> RequestModelBinder[Tctx, Treq]: ...


def initialize[Tctx, Treq: BaseReqModel](cb: InitCb[Tctx, Treq]) -> object:
    params = list(signature(cb).parameters)
    if not params:
        raise BindError(f"'init' 콜백은 요청 인자가 하나 있어야 한다. - {cb.__qualname__}")
    type_hints = get_type_hints(cb)
    print(type_hints)
    first = params[0]
    if first not in type_hints:
        raise BindError(
            f"'init' 콜백의 첫 인자 '{first}'에 요청 타입 어노테이션이 있어야 한다."
            f" - {cb.__qualname__}"
        )
    req_t = type_hints[first]
    bind_pack = BindPack(req_t, cb)
    if issubclass(req_t, GenerateModel):
        return GenerateModelBinder(bind_pack)
    elif issubclass(req_t, DependentModel):
        return DependentModelBinder(bind_pack)
    elif issubclass(req_t, RequestModel):
        return RequestModelBinder(bind_pack)
    else:
        raise BindError(f"지원하는 'RequestModel'이 아니다. - {req_t}")
