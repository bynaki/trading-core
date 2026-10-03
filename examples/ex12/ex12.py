"""binder가 심볼 하나만 거부할 때(`SymbolRejected`) 코어가 어떻게 처리하는지 보여 주는 예제.

원천 generator는 심볼 합집합 하나로 돈다. 한 소비자가 넣은 심볼이 상장 폐지되었거나 오타라서
binder가 그냥 예외를 던지면, 같은 원천을 쓰는 모든 소비자가 실패한다(ex10). binder가 그 심볼을
`SymbolRejected`로 던지면 코어는 피해를 그 심볼로 좁힌다.

    그 심볼만 구독에서 빼고, 그 심볼을 구독한 소비자에게만 **자기 심볼만** 담은 `StageFailed`를
    알린다. 스테이지는 남은 심볼로 generator를 다시 띄운다.

원천 `TickReq`는 `account`로 스테이지를 나눈다. 시작할 때 거래소에 없는 심볼을, 도는 중에는
`run_ex.py`가 `DELISTED`에 넣은 심볼을 거부한다. 파생 `PriceReq`와 세션 `WatchReq`는 그 원천을
상위로 둔다.

generator가 받은 심볼과 detach 횟수, unbind된 심볼은 `계층:계정` 키로 기록해 `run_ex.py`가
판정에 쓴다.
"""

from asyncio import sleep

from trading_core import DataModel, DerivedRequest, SourceRequest, SymbolRejected, initialize
from trading_core.logger import get_logger
from trading_core.model import Receiver, Runnable, SessionRequest, cast_model

origin_log = get_logger("ex12.origin")
derived_log = get_logger("ex12.derived")
session_log = get_logger("ex12.session")

QUOTE_SUFFIX = "/USD"

LISTED: dict[str, float] = {
    "BTC/USD": 68_000.0,
    "ETH/USD": 3_200.0,
    "DOGE/USD": 0.15,
}
"""거래소에 상장된 심볼과 기준가. 여기 없는 심볼은 generator가 시작하자마자 거부한다."""

# 계정별로 상장 폐지된 심볼. `run_ex.py`가 넣으면 그 계정의 generator가 다음 바퀴에 거부한다.
DELISTED: dict[str, set[str]] = {}

# `계층:계정`별 사건 기록. `run_ex.py`가 판정할 때 읽는다.
GEN_STARTS: dict[str, list[list[str]]] = {}
DETACHES: dict[str, int] = {}
UNBOUND: dict[str, list[str]] = {}


def reset() -> None:
    """상장 폐지 목록과 사건 기록을 비운다. `run_ex()`가 시작할 때 부른다."""

    for state in (DELISTED, GEN_STARTS, DETACHES, UNBOUND):
        state.clear()


def delist(account: str, symbol: str) -> None:
    """`account`의 거래소에서 `symbol`을 상장 폐지한다."""

    DELISTED.setdefault(account, set()).add(symbol)


# ===== 원천: 없는 심볼과 상장 폐지된 심볼을 거부한다 =====


class TickReq(SourceRequest):
    """거래소 표기 심볼(`"BTC/USD"`)로 체결가를 요청하는 원천 요청."""

    account: str


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """0.5초 간격으로 체결가를 발행한다. 줄 수 없는 심볼은 `SymbolRejected`로 던진다.

    던지면 이 generator는 끝난다. 남은 심볼로 다시 띄우는 것은 코어가 한다.
    """

    GEN_STARTS.setdefault(f"tick:{ctx.account}", []).append(sorted(symbols))
    origin_log.info("generator 시작", account=ctx.account, upper=sorted(symbols))
    if unknown := symbols - LISTED.keys():
        raise SymbolRejected(unknown, "거래소에 없는 심볼")
    seq = 0
    try:
        while True:
            if delisted := symbols & DELISTED.get(ctx.account, set()):
                raise SymbolRejected(delisted, "상장 폐지")
            for symbol in sorted(symbols):
                yield TickData(symbol=symbol, price=LISTED[symbol] + seq)
            seq += 1
            await sleep(0.5)
    finally:
        origin_log.info("generator 정리", account=ctx.account)


@tick.detached
async def _(ctx: TickReq):
    DETACHES[f"tick:{ctx.account}"] = DETACHES.get(f"tick:{ctx.account}", 0) + 1
    origin_log.info("detach", account=ctx.account)


# ===== 파생: 기초 자산 심볼로 되돌린다 =====


class PriceReq(DerivedRequest):
    """기초 자산 심볼(`"BTC"`)로 체결가를 받는 파생 요청. 상위는 같은 `account`의 `TickReq`다."""

    account: str


class PriceData(DataModel):
    price: float


@PriceReq.require
def _(req: PriceReq, symbols: set[str]):
    return TickReq(account=req.account), {f"{s}{QUOTE_SUFFIX}" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    """상위 체결가의 심볼을 기초 자산으로 되돌려 발행한다. 거부를 모른다."""

    GEN_STARTS.setdefault(f"price:{ctx.account}", []).append(sorted(symbols))
    derived_log.info("generator 시작", account=ctx.account, lower=sorted(symbols))
    while True:
        tick_data = cast_model(await recv(), TickData)
        yield PriceData(symbol=tick_data.symbol.removesuffix(QUOTE_SUFFIX), price=tick_data.price)


# ===== 세션: 심볼마다 슬롯 하나가 같은 원천에 붙는다 =====


class WatchReq(SessionRequest):
    """하위 심볼(`"BTC"`)마다 같은 `account`의 원천에 붙는 세션 요청."""

    account: str


class WatchData(DataModel):
    price: float


class Relay(Runnable):
    """상위 표기의 `TickData`를 하위 표기의 `WatchData`로 옮긴다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: TickData) -> WatchData | None:
        return WatchData(symbol=self.symbol, price=input.price)


@initialize
def watch(req: WatchReq) -> WatchReq:
    return req


@watch
async def _(ctx: WatchReq, symbol: str):
    session_log.info("bind", account=ctx.account, symbol=symbol)
    yield TickReq(account=ctx.account)(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


@watch.unbind
async def _(ctx: WatchReq, symbol: str):
    UNBOUND.setdefault(f"watch:{ctx.account}", []).append(symbol)
    session_log.info("unbind", account=ctx.account, symbol=symbol)
