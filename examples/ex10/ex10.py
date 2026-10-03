"""콜백이 던질 때 코어가 어떻게 처리하는지 보여 주는 예제.

실패를 주입할 수 있는 원천(`TickReq`) · 파생(`PriceReq`) 한 쌍이다. 확인하는 정책은 이렇다.

    코어는 재시도하지 않는다. 실패한 스테이지를 내리고, 영향받은 소비자에게
    **자기 심볼만** 담은 `StageFailed`를 `on_error`로 알린다.

`run_ex.py`가 `TRIPPED`에 요청의 `tag`를 넣으면 그 원천 generator는 다음 발행 직전에
`ConnectionError`를 던진다. 거래소 연결이 끊긴 상황을 흉내 낸 것이다. `fail_on_detach`를 켠
요청은 `detach` 콜백이 던진다. init·generator 시작·detach 횟수는 `tag`별로 기록해
`run_ex.py`가 판정에 쓴다.
"""

from asyncio import sleep

from trading_core import DataModel, DerivedRequest, SourceRequest, initialize
from trading_core.logger import get_logger
from trading_core.model import Receiver, cast_model

# 콜백마다 로거를 따로 둔다. 줄마다 붙는 이름이 어느 계층의 로그인지 알려 준다.
origin_log = get_logger("ex10.origin")
derived_log = get_logger("ex10.derived")

QUOTE_SUFFIX = "/USD"

BASE_PRICE: dict[str, float] = {
    "BTC/USD": 68_000.0,
    "ETH/USD": 3_200.0,
}

# 실패 주입 스위치. 원천 generator는 자기 `tag`가 여기 들면 그것을 빼고 던진다(한 번만).
TRIPPED: set[str] = set()

# `tag`별 사건 횟수. `run_ex.py`가 재시도 여부와 정리 여부를 판정할 때 읽는다.
INITS: dict[str, int] = {}
GEN_STARTS: dict[str, int] = {}
DETACHES: dict[str, int] = {}


def reset() -> None:
    """실패 주입 스위치와 사건 횟수를 비운다. `run_ex()`가 시작할 때 부른다."""

    for state in (TRIPPED, INITS, GEN_STARTS, DETACHES):
        state.clear()


def _bump(counter: dict[str, int], tag: str) -> int:
    counter[tag] = counter.get(tag, 0) + 1
    return counter[tag]


class TickReq(SourceRequest):
    """거래소 표기 심볼(`"BTC/USD"`)로 체결가를 요청하는 원천 요청.

    `tag`가 다르면 content_id가 달라 스테이지도 따로 선다. 시나리오끼리 이것으로 격리한다.
    """

    tag: str
    fail_on_detach: bool = False


class TickData(DataModel):
    price: float
    seq: int


@initialize
def tick(req: TickReq) -> TickReq:
    """요청 자체를 컨텍스트로 쓴다. 스테이지가 새로 설 때마다 불린다."""

    count = _bump(INITS, req.tag)
    origin_log.info(f"init {count}회차", tag=req.tag)
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """0.5초 간격으로 체결가를 발행한다. `TRIPPED`에 걸리면 재연결하지 않고 그대로 던진다.

    무해한 끊김을 버틸지(재연결 등)는 binder가 여기서 스스로 정한다. 코어는 재시도하지 않는다.
    """

    count = _bump(GEN_STARTS, ctx.tag)
    origin_log.info(f"generator {count}회차 시작", tag=ctx.tag, upper=sorted(symbols))
    seq = 0
    try:
        while True:
            if ctx.tag in TRIPPED:
                TRIPPED.discard(ctx.tag)
                raise ConnectionError("거래소 연결이 끊겼다")
            for symbol in sorted(symbols):
                yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + seq, seq=seq)
            seq += 1
            await sleep(0.5)
    finally:
        origin_log.info("generator 정리", tag=ctx.tag)


@tick.detached
async def _(ctx: TickReq):
    """마지막 구독이 빠지거나 스테이지가 실패하면 불린다. 던져도 정리는 끝까지 간다."""

    _bump(DETACHES, ctx.tag)
    origin_log.info("detach", tag=ctx.tag)
    if ctx.fail_on_detach:
        raise RuntimeError("연결을 닫다가 실패했다")


class PriceReq(DerivedRequest):
    """기초 자산 심볼(`"BTC"`)로 체결가를 받는 파생 요청. 상위는 같은 `tag`의 `TickReq`다."""

    tag: str


class PriceData(DataModel):
    price: float


@PriceReq.require
def _(req: PriceReq, symbols: set[str]):
    """하위 심볼(`BTC`)을 상위 표기(`BTC/USD`)로 바꾼다."""

    return TickReq(tag=req.tag), {f"{s}{QUOTE_SUFFIX}" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    """상위 체결가의 심볼을 기초 자산으로 되돌려 발행한다.

    상위가 실패해도 여기서 할 일은 없다. 코어가 이 스테이지까지 내리고 소비자에게 알린다.
    """

    derived_log.info("generator 시작", tag=ctx.tag, lower=sorted(symbols))
    try:
        while True:
            tick_data = cast_model(await recv(), TickData)
            symbol = tick_data.symbol.removesuffix(QUOTE_SUFFIX)
            yield PriceData(symbol=symbol, price=tick_data.price)
    finally:
        derived_log.info("generator 정리", tag=ctx.tag)
