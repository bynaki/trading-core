"""ex16: 구독 심볼과 상관없이 늘 붙는 파이프라인 — `@x.always`

전략 하나가 코인별 가격(심볼마다)과 함께 시장 지수(심볼과 무관하게 하나)를 늘 봐야 한다고 하자.
bind는 구독 심볼마다 불리므로 지수를 bind에 넣으면 심볼 수만큼 중복으로 붙는다. 이럴 때 쓰는 것이
`@x.always`다. 세션 하나에 한 번 불려 파이프라인을 yield하고, 그 파이프라인은 구독 심볼이 무엇이든
(비어 있어도) 세션이 살아 있는 동안 붙어 있다.

    세션 ─┬─ always: IndexReq()("CRYPTO10") | Index()       ← 늘 하나
          ├─ 슬롯 BTC: TickReq()("BTC/USD") | Price("BTC")   ← 심볼마다
          └─ ...

파생 요청의 `require`(상위 요청을 정함)와 이름이 비슷해 보이지만 다른 것이다. always는 "늘 붙는
파이프라인"이다.

배우는 것
- always 콜백은 `(ctx)`만 받는다. 첫 `update()`에서 한 번 불린다 — 빈 집합 `update(set())`이어도.
- always 파이프라인은 bind한 심볼이 아니므로 unbind 대상이 아니다. 구독이 끝날 때 함께 닫힌다.
- 소비자 하나가 서로 다른 모델(지수·가격)을 받는다. 타입으로 나눠 처리한다.

실행
    uv run examples/ex16_always.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex16: ----- 1. update(set()): 심볼 없이 시작 -----
    ex16.portfolio: init
    ex16.portfolio: always
    ex16: 받은 것 {index=3, price=0}
    ex16: ----- 2. update({'BTC'}) -----
    ex16.portfolio: bind {symbol=BTC}
    ex16: ----- 3. 블록을 벗어난다 -----
    ex16.portfolio: unbind {symbol=BTC}
    ex16.portfolio: detached
    ex16: 받은 것 {index=5, price=3}
    (건수는 실행마다 조금씩 다르다)

다음: ex17_source_failure.py — 소스 generator가 던질 때
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    Runnable,
    SessionRequest,
    SourceRequest,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2

log = get_logger("ex16")
portfolio_log = get_logger("ex16.portfolio")

EVENTS: list[str] = []


# ===== binder 쪽 (1): 소스 요청 둘 — 코인 가격과 시장 지수 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=100.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


class IndexReq(SourceRequest):
    pass


class IndexTick(DataModel):
    value: float


@initialize
def index(req: IndexReq) -> IndexReq:
    return req


@index
async def _(ctx: IndexReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield IndexTick(symbol=symbol, value=1000.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 세션 요청 — 지수는 always, 가격은 bind =====


class PortfolioReq(SessionRequest):
    pass


class IndexData(DataModel):
    value: float


class PriceData(DataModel):
    price: float


class Index(Runnable[IndexTick, IndexData]):
    async def invoke(self, input: IndexTick) -> IndexData:
        return IndexData(symbol="INDEX", value=input.value)


class Price(Runnable[TickData, PriceData]):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: TickData) -> PriceData:
        return PriceData(symbol=self.symbol, price=input.price)


@initialize
def portfolio(req: PortfolioReq) -> PortfolioReq:
    portfolio_log.info("init")
    EVENTS.append("init")
    return req


@portfolio.always
async def _(ctx: PortfolioReq):
    """심볼 인자가 없다. 세션에 한 번 불린다."""

    portfolio_log.info("always")
    EVENTS.append("always")
    yield IndexReq()("CRYPTO10") | Index()


@portfolio
async def _(ctx: PortfolioReq, symbol: str):
    portfolio_log.info("bind", symbol=symbol)
    EVENTS.append(f"bind {symbol}")
    yield TickReq()(f"{symbol}/USD") | Price(symbol)


@portfolio.unbind
async def _(ctx: PortfolioReq, symbol: str):
    portfolio_log.info("unbind", symbol=symbol)
    EVENTS.append(f"unbind {symbol}")


@portfolio.detached
async def _(ctx: PortfolioReq):
    portfolio_log.info("detached")
    EVENTS.append("detached")


# ===== 소비자 쪽 =====


class Recorder:
    """지수와 가격을 타입으로 나눠 센다."""

    def __init__(self) -> None:
        self.index = 0
        self.price = 0

    async def __call__(self, data: DataModel) -> None:
        if isinstance(data, IndexData):
            self.index += 1
        elif isinstance(data, PriceData):
            self.price += 1


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 늘 붙는 파이프라인 @x.always ━━━━━━━━━━")
    EVENTS.clear()
    got = Recorder()

    async with domain.subscribe(PortfolioReq(), got) as sub:
        log.info("----- 1. update(set()): 심볼 없이 시작 -----")
        await sub.update(set())
        await asyncio.sleep(0.5)
        log.info("받은 것", index=got.index, price=got.price)
        assert got.index > 0 and got.price == 0  # 심볼이 없어도 지수는 온다

        log.info("----- 2. update({'BTC'}) -----")
        await sub.update({"BTC"})
        await asyncio.sleep(0.5)

        log.info("----- 3. 블록을 벗어난다 -----")
    log.info("받은 것", index=got.index, price=got.price)

    assert got.price > 0
    assert EVENTS == [
        "init",
        "always",  # 한 번. 심볼을 더해도 다시 불리지 않는다
        "bind BTC",
        "unbind BTC",  # always 파이프라인은 unbind되지 않는다
        "detached",
    ], EVENTS
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
