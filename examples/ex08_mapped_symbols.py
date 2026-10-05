"""ex08: 상위가 심볼을 다르게 부를 때 — 심볼까지 바꾸는 `require`

소비자는 `"BTC"`라고 부르는데 거래소는 `"BTC/USD"`라고 부른다. 소비자에게 거래소 표기를 강요하지
않으려면 파생 요청이 두 표기 사이를 오가야 한다.

    소비자 {"BTC"} ─→ require가 바꿈 ─→ 소스 스테이지 {"BTC/USD"}
    소비자 ←── "BTC" ←── 파생 generator가 되돌림 ←── "BTC/USD" 데이터

- **내려갈 때(하위 → 상위)**: `require` 콜백이 심볼 집합도 받아 `(상위 요청, 상위 심볼)`을 돌려준다.
- **올라올 때(상위 → 하위)**: 파생 generator가 데이터의 `symbol`을 하위 표기로 되돌려 yield한다.

되돌리지 않으면 어떻게 될까? 데이터는 `symbol`로 소비자를 찾는다(ex05). `"BTC/USD"`를 구독한
소비자는 없으므로 데이터는 버려진다. 소비자에게는 **오류도 없이** 아무것도 오지 않고, 남는 것은
`trading_core.routing`의 WARNING 로그뿐이다. 이 예제의 두 번째 단계가 이 실수를 일부러 보인다.

배우는 것
- 심볼까지 받는 `require`는 `(req, symbols)`를 받는다. `symbols`는 그 파생 스테이지의 심볼
  합집합이다.
- 파생 generator의 `symbols`는 하위 표기, `recv()`로 오는 데이터는 상위 표기다.
- 되돌리기를 잊으면 소비자는 조용히 아무것도 못 받는다.

실행
    uv run examples/ex08_mapped_symbols.py

기대 출력 (줄 앞의 레벨 `INFO  `·`WARNING`은 뺐다)
    ex08: ----- 1. 되돌리는 파생 요청: A는 {'BTC'}, B는 {'ETH'} -----
    ex08.price: require {lower=['BTC'], upper=['BTC/USD']}
    ex08.price: require {lower=['BTC', 'ETH'], upper=['BTC/USD', 'ETH/USD']}
    ex08: 표기별 심볼 {derived=['BTC', 'ETH'], source=['BTC/USD', 'ETH/USD']}
    ex08.price: generator 시작 {symbols=['BTC', 'ETH']}
    ex08.price: require {lower=['BTC'], upper=['BTC/USD']}
    ex08: 받은 심볼 {a=['BTC'], b=['ETH']}
    ex08: ----- 2. 되돌리기를 잊은 파생 요청: C는 {'BTC'} -----
    ex08: 표기별 심볼 {derived=['BTC'], source=['BTC/USD']}
    trading_core.routing: 데이터를 전송할 Sender가 없다 {symbol=BTC/USD}
    trading_core.routing: 데이터를 전송할 Sender가 없다 {symbol=BTC/USD}
    ...
    ex08: C가 받은 건수 {c=0}

require는 파생 스테이지의 합집합이 바뀔 때마다 불린다. 1단계 끝의 require 줄은 블록을 벗어나며 B가
먼저 빠져 합집합이 `{BTC}`로 줄었기 때문이다.

다음: ex09_choose_upstream.py — 요청 필드에 따라 다른 거래소에 붙기
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    DerivedRequest,
    Domain,
    Receiver,
    SourceRequest,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
BASE_PRICE = {"BTC/USD": 100.0, "ETH/USD": 200.0}
"""거래소 표기로 된 시작 가격. 하위 표기(`"BTC"`)가 잘못 내려오면 KeyError로 드러난다."""

log = get_logger("ex08")
price_log = get_logger("ex08.price")


def to_upper(symbol: str) -> str:
    """하위 표기 → 상위 표기. `"BTC"` → `"BTC/USD"`."""

    return f"{symbol}/USD"


def to_lower(symbol: str) -> str:
    """상위 표기 → 하위 표기. `"BTC/USD"` → `"BTC"`."""

    return symbol.removesuffix("/USD")


# ===== binder 쪽 (1): 소스 요청 — 거래소 표기를 쓴다 =====


class TickReq(SourceRequest):
    exchange: str


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """`symbols`는 거래소 표기(`"BTC/USD"`)다."""

    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 파생 요청 — 표기를 바꾸고 되돌린다 =====


class PriceReq(DerivedRequest):
    """소비자 표기(`"BTC"`)로 체결가를 받는 요청."""


class PriceData(DataModel):
    price: float


@PriceReq.require
def _(req: PriceReq, symbols: set[str]) -> tuple[TickReq, set[str]]:
    """내려가는 변환. 인자가 둘이면 심볼까지 바꾸는 형태로 등록된다.

    `symbols`는 이 파생 스테이지의 심볼 합집합이다. 소비자가 바뀌어 합집합이 바뀔 때마다 불린다.
    """

    upper = {to_upper(s) for s in symbols}
    price_log.info("require", lower=sorted(symbols), upper=sorted(upper))
    return TickReq(exchange="mock"), upper


@initialize
def price(req: PriceReq) -> PriceReq:
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    """올라오는 변환. `symbols`는 하위 표기, `recv()`의 데이터는 상위 표기다."""

    price_log.info("generator 시작", symbols=sorted(symbols))
    while True:
        tick = cast_model(await recv(), TickData)
        yield PriceData(symbol=to_lower(tick.symbol), price=tick.price)  # 되돌린다


# ===== binder 쪽 (3): 되돌리기를 잊은 파생 요청 (일부러 틀림) =====


class ForgetfulPriceReq(DerivedRequest):
    """`PriceReq`와 같지만 generator가 심볼을 되돌리지 않는다."""


@ForgetfulPriceReq.require
def _(req: ForgetfulPriceReq, symbols: set[str]) -> tuple[TickReq, set[str]]:
    return TickReq(exchange="mock"), {to_upper(s) for s in symbols}


@initialize
def forgetful(req: ForgetfulPriceReq) -> ForgetfulPriceReq:
    return req


@forgetful
async def _(ctx: ForgetfulPriceReq, symbols: set[str], recv: Receiver):
    while True:
        tick = cast_model(await recv(), TickData)
        yield PriceData(symbol=tick.symbol, price=tick.price)  # "BTC/USD" 그대로 — 실수


# ===== 소비자 쪽 =====


class Recorder:
    def __init__(self) -> None:
        self.symbols: set[str] = set()
        self.count = 0

    async def __call__(self, data: DataModel) -> None:
        self.symbols.add(data.symbol)
        self.count += 1


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 심볼까지 바꾸는 require ━━━━━━━━━━")
    a, b, c = Recorder(), Recorder(), Recorder()

    log.info("----- 1. 되돌리는 파생 요청: A는 {'BTC'}, B는 {'ETH'} -----")
    async with (
        domain.subscribe(PriceReq(), a) as sub_a,
        domain.subscribe(PriceReq(), b) as sub_b,
    ):
        await sub_a.update({"BTC"})
        await sub_b.update({"ETH"})
        derived = domain.get_shared_symbols(PriceReq().tr_content_id)
        source = domain.get_shared_symbols(TickReq(exchange="mock").tr_content_id)
        log.info("표기별 심볼", derived=sorted(derived), source=sorted(source))
        await asyncio.sleep(0.5)
    log.info("받은 심볼", a=sorted(a.symbols), b=sorted(b.symbols))

    assert derived == {"BTC", "ETH"}  # 파생 스테이지는 하위 표기의 합집합
    assert source == {"BTC/USD", "ETH/USD"}  # 소스 스테이지는 그것을 바꾼 상위 표기
    assert a.symbols == {"BTC"} and b.symbols == {"ETH"}

    log.info("----- 2. 되돌리기를 잊은 파생 요청: C는 {'BTC'} -----")
    async with domain.subscribe(ForgetfulPriceReq(), c) as sub_c:
        await sub_c.update({"BTC"})
        derived = domain.get_shared_symbols(ForgetfulPriceReq().tr_content_id)
        source = domain.get_shared_symbols(TickReq(exchange="mock").tr_content_id)
        log.info("표기별 심볼", derived=sorted(derived), source=sorted(source))
        await asyncio.sleep(0.5)
    log.info("C가 받은 건수", c=c.count)

    assert source == {"BTC/USD"}  # 상위까지는 제대로 내려갔다
    assert c.count == 0  # 예외도 on_error도 없다. 그냥 아무것도 오지 않는다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    try:
        await run_ex(domain)
    finally:
        await domain.stop()


if __name__ == "__main__":
    asyncio.run(main())
