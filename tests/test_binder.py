"""`binder.py` 명세 — `initialize()` 등록 규칙과 전역 레지스트리.

여기서 쓰는 요청 모델은 모두 이 모듈 전용이다. `BindPack._binder_dict`가 프로세스
전역이라 다른 테스트 모듈과 요청 타입을 공유하면 등록이 서로 간섭한다.
"""

from collections.abc import AsyncGenerator

import pytest

from trading_core import (
    BindError,
    DataModel,
    DependentModel,
    DependentModelBinder,
    GenerateModel,
    GenerateModelBinder,
    ModelError,
    Receiver,
    RequestModel,
    RequestModelBinder,
    Sequence,
    get_model_id,
    get_model_type,
    initialize,
)
from trading_core.binder import BindPack


class GenReq(GenerateModel):
    """generate 콜백을 바인드할 원천 요청."""

    tag: str


class DepReq(DependentModel):
    """`GenReq`를 상위로 요구하는 파생 요청."""

    tag: str


class SymDepReq(DependentModel):
    """심볼까지 변환하는 require 콜백을 쓰는 파생 요청."""

    tag: str


class NoRequireReq(DependentModel):
    """require를 일부러 등록하지 않은 파생 요청."""

    tag: str


class ReqReq(RequestModel):
    """bind/unbind/require 콜백을 붙일 요청."""

    tag: str


class PlainData(DataModel):
    """요청 모델이 아닌 모델. `initialize()` 거부 검증에 쓴다."""

    value: str


# ===== 원천 제너레이터 등록 =====


@initialize
def gen_binder(req: GenReq) -> GenReq:
    """요청 자체를 컨텍스트로 쓰는 init 콜백."""

    return req


@gen_binder
async def _(ctx: GenReq, symbols: set[str]) -> AsyncGenerator[DataModel]:
    """검증에는 쓰지 않고 등록만 하는 generate 콜백."""

    yield PlainData(symbol=ctx.tag, value=",".join(sorted(symbols)))


@gen_binder.detached
async def _(ctx: GenReq) -> None:
    """등록만 하는 detach 콜백."""


def test_initialize_returns_generate_binder():
    """`GenerateModel`을 받는 init 콜백은 `GenerateModelBinder`를 낸다."""

    assert isinstance(gen_binder, GenerateModelBinder)


def test_generate_binding_marks_model_type():
    """generate 콜백을 바인드하면 요청 타입이 "generator"가 된다."""

    assert get_model_type(GenReq) == "generator"


def test_bind_pack_is_registered_by_model_id():
    """레지스트리는 `model_id`를 키로 쓴다."""

    pack = BindPack.get_binder(get_model_id(GenReq))
    assert pack is not None
    assert pack.request_t is GenReq
    assert pack.get_generate_cb() is not None
    assert pack.get_detach_cb() is not None


def test_unknown_model_id_has_no_binder():
    """등록되지 않은 `model_id`는 `None`."""

    assert BindPack.get_binder("NoSuchModel@nowhere:0000000000000000") is None


def test_rebinding_generate_callback_is_rejected():
    """같은 요청 타입에 generate 콜백을 두 번 바인드할 수 없다."""

    async def other(ctx: GenReq, symbols: set[str]) -> AsyncGenerator[DataModel]:
        yield PlainData(value="other")

    with pytest.raises(BindError):
        gen_binder.generate(other)


def test_duplicate_initialize_is_rejected():
    """같은 요청 타입으로 `initialize()`를 두 번 부를 수 없다."""

    def init(req: GenReq) -> GenReq:
        return req

    with pytest.raises(BindError):
        initialize(init)


# ===== init 콜백 시그니처 =====


def test_initialize_requires_a_request_parameter():
    """init 콜백에는 요청 인자가 하나 있어야 한다."""

    def init() -> None:
        return None

    with pytest.raises(BindError):
        initialize(init)  # type: ignore[arg-type]


def test_initialize_requires_annotation_on_first_parameter():
    """요청 타입은 첫 인자의 어노테이션으로 추론하므로 어노테이션이 없으면 실패한다."""

    def init(req) -> None:  # type: ignore[no-untyped-def]
        return None

    with pytest.raises(BindError):
        initialize(init)  # type: ignore[arg-type]


def test_initialize_rejects_non_request_model():
    """요청 계열이 아닌 모델은 등록할 수 없다."""

    def init(req: PlainData) -> PlainData:
        return req

    with pytest.raises(BindError):
        initialize(init)  # type: ignore[arg-type]


# ===== 파생 제너레이터와 require =====


@DepReq.require
def _(req: DepReq) -> GenReq:
    """요청만 받아 상위 요청을 돌려주는 `RequireCb` 형태."""

    return GenReq(tag=req.tag)


@initialize
def dep_binder(req: DepReq) -> DepReq:
    """파생 요청의 init 콜백."""

    return req


@dep_binder
async def _(ctx: DepReq, symbols: set[str], recv: Receiver) -> AsyncGenerator[DataModel]:
    """등록만 하는 dependent 콜백."""

    yield PlainData(value=ctx.tag)


@SymDepReq.require
def _(req: SymDepReq, symbols: set[str]) -> tuple[GenReq, set[str]]:
    """심볼 집합까지 변환하는 `RequireCbWithSym` 형태."""

    return GenReq(tag=req.tag), {f"{s}/USD" for s in symbols}


def test_initialize_returns_dependent_binder():
    """`DependentModel`을 받는 init 콜백은 `DependentModelBinder`를 낸다."""

    assert isinstance(dep_binder, DependentModelBinder)


def test_dependent_binding_marks_model_type():
    """dependent 콜백을 바인드하면 요청 타입이 "dependent_generator"가 된다."""

    assert get_model_type(DepReq) == "dependent_generator"


def test_plain_require_passes_symbols_through():
    """요청만 받는 require는 심볼 집합을 그대로 흘려보내도록 정규화된다."""

    req = DepReq(tag="t")
    assert req.tr_require.get_tr_content_id() == GenReq(tag="t").get_tr_content_id()

    upstream, symbols = req.get_tr_require_with_symbol({"BTC", "ETH"})
    assert upstream.get_tr_content_id() == GenReq(tag="t").get_tr_content_id()
    assert symbols == {"BTC", "ETH"}


def test_require_with_symbols_transforms_symbols():
    """심볼까지 받는 require는 상위에 넘길 심볼을 바꿀 수 있다."""

    upstream, symbols = SymDepReq(tag="t").get_tr_require_with_symbol({"BTC", "ETH"})
    assert upstream.get_tr_content_id() == GenReq(tag="t").get_tr_content_id()
    assert symbols == {"BTC/USD", "ETH/USD"}


def test_missing_require_raises_on_use():
    """require가 없는 파생 요청은 상위 요청을 물었을 때 `ModelError`."""

    with pytest.raises(ModelError):
        _ = NoRequireReq(tag="t").tr_require
    with pytest.raises(ModelError):
        NoRequireReq(tag="t").get_tr_require_with_symbol({"BTC"})


def test_require_is_registered_per_subclass():
    """require 콜백은 파생 요청 클래스마다 따로 보관된다."""

    assert DepReq._tr_require_cb is not None
    assert NoRequireReq._tr_require_cb is None


# ===== RequestModel =====


@initialize
def req_binder(req: ReqReq) -> ReqReq:
    """요청형 모델의 init 콜백."""

    return req


@req_binder
async def _(ctx: ReqReq, symbol: str) -> Sequence:
    """심볼 하나를 시퀀스로 묶는 bind 콜백."""

    return ctx(symbol)


def test_initialize_returns_request_binder():
    """`RequestModel`을 받는 init 콜백은 `RequestModelBinder`를 낸다."""

    assert isinstance(req_binder, RequestModelBinder)


def test_request_binding_marks_model_type():
    """bind 콜백을 붙이면 요청 타입이 "request"가 된다."""

    assert get_model_type(ReqReq) == "request"


def test_request_binder_collects_bind_and_require_callbacks():
    """bind · require 콜백은 여러 개를 모아 둔다."""

    async def another_bind(ctx: ReqReq, symbol: str) -> Sequence:
        return ctx(symbol)

    async def requirement(ctx: ReqReq) -> Sequence:
        return ctx("BTC")

    req_binder.bind(another_bind).require(requirement)

    pack = BindPack.get_binder(get_model_id(ReqReq))
    assert pack is not None
    assert len(pack.get_bind_cb_set()) == 2
    assert len(pack.get_require_cb_set()) == 1


def test_unbind_callback_can_only_be_set_once():
    """unbind 콜백은 하나만 등록할 수 있다."""

    async def unbind(ctx: ReqReq, symbol: str) -> None:
        return None

    req_binder.unbind(unbind)
    with pytest.raises(BindError):
        req_binder.unbind(unbind)
