"""init 콜백이 던질 때 코어가 어떻게 처리하는지 보여 주는 예제.

init 콜백은 스테이지가 설 때 한 번 불려 컨텍스트를 만든다. 거래소 로그인처럼 실패할 수 있는 일을
여기서 하기 쉽다. 확인하는 정책은 이렇다.

    init이 던지면 스테이지를 세우지 않고, 그 스테이지를 쓰려던 소비자에게 **자기 심볼만** 담은
    `StageFailed`를 `on_error`로 알린다. `update()`·`subscribe()`는 던지지 않는다.

원천 `TickReq`는 `account`로 거래소에 로그인하는 흉내를 낸다. `run_ex.py`가 `REFUSED`에 계정을
넣으면 그 계정의 다음 로그인(init)이 한 번 `PermissionError`를 던진다. 파생 `PriceReq`는 그 원천을
상위로 두고, 세션 `WatchReq`는 심볼마다 다른 계정(`{name}:{symbol}`)의 원천에 붙는다. 세션 자신의
init도 `REFUSED`에 `name`이 들면 던진다.

init 시도·generator 시작·detach 횟수와 unbind된 심볼은 `계층:이름` 키로 기록해 `run_ex.py`가
판정에 쓴다.
"""

from asyncio import sleep

from trading_core import DataModel, DerivedRequest, SourceRequest, initialize
from trading_core.logger import get_logger
from trading_core.model import Receiver, Runnable, SessionRequest, cast_model

# 콜백마다 로거를 따로 둔다. 줄마다 붙는 이름이 어느 계층의 로그인지 알려 준다.
origin_log = get_logger("ex11.origin")
derived_log = get_logger("ex11.derived")
session_log = get_logger("ex11.session")

QUOTE_SUFFIX = "/USD"

BASE_PRICE: dict[str, float] = {
    "BTC/USD": 68_000.0,
    "ETH/USD": 3_200.0,
}

# 실패 주입 스위치. 계정(원천)이나 이름(세션)이 여기 들면 다음 init이 그것을 빼고 던진다(한 번만).
REFUSED: set[str] = set()

# `계층:이름`별 사건 기록. `run_ex.py`가 판정할 때 읽는다.
INITS: dict[str, int] = {}
GEN_STARTS: dict[str, int] = {}
DETACHES: dict[str, int] = {}
UNBOUND: dict[str, list[str]] = {}


def reset() -> None:
    """실패 주입 스위치와 사건 기록을 비운다. `run_ex()`가 시작할 때 부른다."""

    for state in (REFUSED, INITS, GEN_STARTS, DETACHES, UNBOUND):
        state.clear()


def _bump(counter: dict[str, int], key: str) -> int:
    counter[key] = counter.get(key, 0) + 1
    return counter[key]


def _refuse_once(name: str) -> bool:
    """`name`이 `REFUSED`에 있으면 빼고 `True`를 돌려준다."""

    if name in REFUSED:
        REFUSED.discard(name)
        return True
    return False


# ===== 원천: 계정으로 로그인해 체결가를 받는다 =====


class TickReq(SourceRequest):
    """거래소 표기 심볼(`"BTC/USD"`)로 체결가를 요청하는 원천 요청.

    `account`가 다르면 content_id가 달라 스테이지도 따로 선다. 시나리오끼리 이것으로 격리한다.
    """

    account: str


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    """거래소에 로그인한다. 거부되면 던진다 — 스테이지는 서지 않는다."""

    count = _bump(INITS, f"tick:{req.account}")
    origin_log.info(f"로그인 {count}회차", account=req.account)
    if _refuse_once(req.account):
        raise PermissionError("API 키가 거부되었다")
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """0.5초 간격으로 체결가를 발행한다. init이 성공한 스테이지에서만 불린다."""

    _bump(GEN_STARTS, f"tick:{ctx.account}")
    origin_log.info("generator 시작", account=ctx.account, upper=sorted(symbols))
    seq = 0
    try:
        while True:
            for symbol in sorted(symbols):
                yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + seq)
            seq += 1
            await sleep(0.5)
    finally:
        origin_log.info("generator 정리", account=ctx.account)


@tick.detached
async def _(ctx: TickReq):
    """init이 성공해 선 스테이지가 내려갈 때만 불린다. init이 던졌으면 정리할 컨텍스트도 없다."""

    _bump(DETACHES, f"tick:{ctx.account}")
    origin_log.info("detach", account=ctx.account)


# ===== 파생: 원천을 상위로 두고 기초 자산 심볼로 되돌린다 =====


class PriceReq(DerivedRequest):
    """기초 자산 심볼(`"BTC"`)로 체결가를 받는 파생 요청. 상위는 같은 `account`의 `TickReq`다."""

    account: str


class PriceData(DataModel):
    price: float


@PriceReq.require
def _(req: PriceReq, symbols: set[str]):
    """하위 심볼(`BTC`)을 상위 표기(`BTC/USD`)로 바꾼다."""

    return TickReq(account=req.account), {f"{s}{QUOTE_SUFFIX}" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    """파생 자신의 init은 늘 성공한다. 실패는 상위(원천)의 init에서 난다."""

    _bump(INITS, f"price:{req.account}")
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    """상위 체결가의 심볼을 기초 자산으로 되돌려 발행한다. 상위가 서야 시작한다."""

    _bump(GEN_STARTS, f"price:{ctx.account}")
    derived_log.info("generator 시작", account=ctx.account, lower=sorted(symbols))
    try:
        while True:
            tick_data = cast_model(await recv(), TickData)
            symbol = tick_data.symbol.removesuffix(QUOTE_SUFFIX)
            yield PriceData(symbol=symbol, price=tick_data.price)
    finally:
        derived_log.info("generator 정리", account=ctx.account)


@price.detached
async def _(ctx: PriceReq):
    _bump(DETACHES, f"price:{ctx.account}")
    derived_log.info("detach", account=ctx.account)


# ===== 세션: 심볼마다 다른 계정의 원천에 붙는다 =====


class WatchReq(SessionRequest):
    """하위 심볼(`"BTC"`)마다 계정 `{name}:{symbol}`의 원천에 붙는 세션 요청."""

    name: str


class WatchData(DataModel):
    price: float


class Relay(Runnable):
    """상위 표기의 `TickData`를 하위 표기의 `WatchData`로 옮긴다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: TickData) -> WatchData | None:
        return WatchData(symbol=self.symbol, price=input.price)


def watch_account(name: str, symbol: str) -> str:
    """세션 `name`의 하위 심볼 `symbol`이 쓰는 원천 계정."""

    return f"{name}:{symbol}"


@initialize
def watch(req: WatchReq) -> WatchReq:
    """세션 저장소를 연다. 거부되면 던진다.

    세션 init은 `subscribe()`가 아니라 첫 `update()`에서 불린다.
    """

    count = _bump(INITS, f"watch:{req.name}")
    session_log.info(f"세션 init {count}회차", name=req.name)
    if _refuse_once(req.name):
        raise PermissionError("세션 저장소를 열지 못했다")
    return req


@watch
async def _(ctx: WatchReq, symbol: str):
    """하위 심볼 하나를 그 심볼 전용 계정의 원천에 잇는다."""

    session_log.info("bind", name=ctx.name, symbol=symbol)
    upstream = TickReq(account=watch_account(ctx.name, symbol))
    yield upstream(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


@watch.unbind
async def _(ctx: WatchReq, symbol: str):
    UNBOUND.setdefault(f"watch:{ctx.name}", []).append(symbol)
    session_log.info("unbind", name=ctx.name, symbol=symbol)


@watch.detached
async def _(ctx: WatchReq):
    _bump(DETACHES, f"watch:{ctx.name}")
    session_log.info("detach", name=ctx.name)


# ===== 등록하지 않은 요청 =====


class UnboundReq(SourceRequest):
    """binder를 일부러 등록하지 않은 요청. init 실패와 등록 오류가 어떻게 다른지 보인다."""
