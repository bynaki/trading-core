from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import aclosing
from inspect import signature
from typing import Any, get_type_hints, overload

from trading_core.exceptions import BindError
from trading_core.model import (
    BaseRequest,
    DataModel,
    DerivedRequest,
    Pipeline,
    Receiver,
    SessionRequest,
    SourceRequest,
    get_model_id,
)

type InitCb[Tctx, Treq: BaseRequest] = Callable[[Treq], Tctx]
type SourceCb[Tctx] = Callable[[Tctx, set[str]], AsyncGenerator[DataModel]]
type DerivedCb[Tctx] = Callable[[Tctx, set[str], Receiver], AsyncGenerator[DataModel]]
type DetachCb[Tctx] = Callable[[Tctx], Coroutine[Any, Any, None]]
type BindCb[Tctx] = Callable[[Tctx, str], AsyncGenerator[Pipeline]]
type UnbindCb[Tctx] = Callable[[Tctx, str], Coroutine[Any, Any, None]]
type AlwaysCb[Tctx] = Callable[[Tctx], AsyncGenerator[Pipeline]]


class BindPack[Tctx, Treq: BaseRequest]:
    _registry: dict[str, BindPack] = {}

    def __init__(self, request_type: type[Treq], init_cb: InitCb[Tctx, Treq]) -> None:
        model_id = get_model_id(request_type)
        if self._registry.get(model_id):
            raise BindError(f"이미 'binder'가 있다. - {model_id}")
        self._registry[model_id] = self
        self._request_type: type[Treq] = request_type
        self._init_cb: InitCb[Tctx, Treq] = init_cb
        self._source_cb: SourceCb[Tctx] | None = None
        self._derived_cb: DerivedCb[Tctx] | None = None
        self._bind_cb: BindCb[Tctx] | None = None
        self._unbind_cb: UnbindCb[Tctx] | None = None
        self._always_cb: AlwaysCb[Tctx] | None = None
        self._detach_cb: DetachCb[Tctx] | None = None

    @classmethod
    def lookup(cls, model_id: str) -> BindPack | None:
        return cls._registry.get(model_id)

    @property
    def request_type(self) -> type[Treq]:
        return self._request_type

    def get_init_cb(self) -> InitCb[Tctx, Treq]:
        return self._init_cb

    def set_source_cb(self, cb: SourceCb[Tctx]):
        if not issubclass(self._request_type, SourceRequest):
            raise BindError("'SourceRequest'가 아니다.")
        if self._request_type._tr_model_type != "unregistered":
            raise BindError(
                f"같은 'SourceRequest'가 이미 등록되어 있다 - ({get_model_id(self._request_type)})"
            )
        self._request_type._tr_model_type = "source"
        self._source_cb = cb

    def get_source_cb(self, req: BaseRequest) -> SourceCb[Tctx] | None:
        cb = self._source_cb
        if cb is None:
            return None
        req_content_id = req.tr_content_id

        async def wrap(ctx: Tctx, symbols: set[str]):
            async with aclosing(cb(ctx, symbols)) as agen:
                async for data in agen:
                    data._tr_req_content_id = req_content_id
                    yield data

        return wrap

    def set_derived_cb(self, cb: DerivedCb[Tctx]):
        if not issubclass(self._request_type, DerivedRequest):
            raise BindError(f"'DerivedRequest'가 아니다. - {get_model_id(self._request_type)}")
        if self._request_type._tr_model_type != "unregistered":
            raise BindError(
                f"같은 'DerivedRequest'가 이미 등록되어 있다 - ({get_model_id(self._request_type)})"
            )
        self._request_type._tr_model_type = "derived"
        self._derived_cb = cb

    def get_derived_cb(self, req: BaseRequest) -> DerivedCb[Tctx] | None:
        if self._derived_cb is None:
            return None
        cb = self._derived_cb
        req_content_id = req.tr_content_id

        async def wrap(ctx: Tctx, symbols: set[str], recv: Receiver) -> AsyncGenerator[DataModel]:
            async with aclosing(cb(ctx, symbols, recv)) as agen:
                async for data in agen:
                    data._tr_req_content_id = req_content_id
                    yield data

        return wrap

    def set_bind_cb(self, cb: BindCb[Tctx]):
        if not issubclass(self._request_type, SessionRequest):
            raise BindError(f"'SessionRequest'가 아니다. - {get_model_id(self._request_type)}")
        if self._request_type._tr_model_type != "unregistered":
            raise BindError(
                f"같은 'SessionRequest'가 이미 등록되어 있다 - ({get_model_id(self._request_type)})"
            )
        self._request_type._tr_model_type = "session"
        self._bind_cb = cb

    def get_bind_cb(self) -> BindCb[Tctx] | None:
        return self._bind_cb

    def set_unbind_cb(self, cb: UnbindCb[Tctx]):
        if not issubclass(self._request_type, SessionRequest):
            raise BindError(f"'SessionRequest'가 아니다. - {get_model_id(self._request_type)}")
        if self._unbind_cb is not None:
            raise BindError(f"'unbind'가 이미 바인드 되었다. - {get_model_id(self._request_type)}")
        self._unbind_cb = cb

    def get_unbind_cb(self) -> UnbindCb[Tctx] | None:
        return self._unbind_cb

    def set_always_cb(self, cb: AlwaysCb[Tctx]):
        if not issubclass(self._request_type, SessionRequest):
            raise BindError(f"'SessionRequest'가 아니다. - {get_model_id(self._request_type)}")
        if self._always_cb is not None:
            raise BindError(f"'always'가 이미 바인드 되었다. - {get_model_id(self._request_type)}")
        self._always_cb = cb

    def get_always_cb(self) -> AlwaysCb[Tctx] | None:
        return self._always_cb

    def set_detach_cb(self, cb: DetachCb[Tctx]):
        self._detach_cb = cb

    def get_detach_cb(self) -> DetachCb[Tctx] | None:
        return self._detach_cb


class BaseBinder[Tctx, Treq: BaseRequest]:
    def __init__(self, pack: BindPack[Tctx, Treq]):
        self._pack = pack

    def detached(self, cb: DetachCb[Tctx]) -> DetachCb[Tctx]:
        self._pack.set_detach_cb(cb)
        return cb


class SourceBinder[Tctx, Treq: SourceRequest](BaseBinder[Tctx, Treq]):
    def __call__(self, cb: SourceCb[Tctx]) -> SourceBinder:
        return self.generate(cb)

    def generate(self, cb: SourceCb[Tctx]):
        self._pack.set_source_cb(cb)
        return self


class DerivedBinder[Tctx, Treq: DerivedRequest](BaseBinder[Tctx, Treq]):
    def __call__(self, cb: DerivedCb[Tctx]) -> DerivedBinder:
        return self.generate(cb)

    def generate(self, cb: DerivedCb[Tctx]):
        self._pack.set_derived_cb(cb)
        return self


class SessionBinder[Tctx, Treq: SessionRequest](BaseBinder[Tctx, Treq]):
    def __call__(self, cb: BindCb[Tctx]) -> SessionBinder:
        return self.bind(cb)

    def bind(self, cb: BindCb[Tctx]) -> SessionBinder[Tctx, Treq]:
        self._pack.set_bind_cb(cb)
        return self

    def unbind(self, cb: UnbindCb[Tctx]) -> SessionBinder[Tctx, Treq]:
        self._pack.set_unbind_cb(cb)
        return self

    def always(self, cb: AlwaysCb[Tctx]) -> SessionBinder[Tctx, Treq]:
        """구독 심볼과 상관없이 늘 붙는 파이프라인을 등록한다."""
        self._pack.set_always_cb(cb)
        return self


@overload
def initialize[Tctx, Treq: SourceRequest](
    cb: InitCb[Tctx, Treq],
) -> SourceBinder[Tctx, Treq]: ...


@overload
def initialize[Tctx, Treq: DerivedRequest](
    cb: InitCb[Tctx, Treq],
) -> DerivedBinder[Tctx, Treq]: ...


@overload
def initialize[Tctx, Treq: SessionRequest](
    cb: InitCb[Tctx, Treq],
) -> SessionBinder[Tctx, Treq]: ...


def initialize[Tctx, Treq: BaseRequest](cb: InitCb[Tctx, Treq]) -> object:
    params = list(signature(cb).parameters)
    if not params:
        raise BindError(f"'init' 콜백은 요청 인자가 하나 있어야 한다. - {cb.__qualname__}")
    type_hints = get_type_hints(cb)
    first = params[0]
    if first not in type_hints:
        raise BindError(
            f"'init' 콜백의 첫 인자 '{first}'에 요청 타입 어노테이션이 있어야 한다."
            f" - {cb.__qualname__}"
        )
    request_type = type_hints[first]
    bind_pack = BindPack(request_type, cb)
    if issubclass(request_type, SourceRequest):
        return SourceBinder(bind_pack)
    elif issubclass(request_type, DerivedRequest):
        return DerivedBinder(bind_pack)
    elif issubclass(request_type, SessionRequest):
        return SessionBinder(bind_pack)
    else:
        raise BindError(f"지원하는 요청 타입이 아니다. - {request_type}")
