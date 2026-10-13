"""ex23: always 파이프라인이 실패할 때 — 세션 전체가 실패한다

ex22에서 본 세션의 실패는 심볼 하나로 끝났다. `@x.always` 파이프라인(ex16)은 다르다. always는
특정 심볼의 것이 아니라 **세션 전체가 기대는 것**(시장 지수, 계좌 잔고 등)이기 때문이다. 그래서
always 슬롯이 실패하면 코어는 세션을 통째로 내린다.

    bind한 심볼을 모두 unbind하고, `@detached`로 컨텍스트를 정리한다. 소비자는 그때 열려 있던
    심볼 모두를 `StageFailed`로 받는다. 구독 객체는 살아 있어서, 다음 `update()`가 init부터
    (always까지) 다시 세운다.

배우는 것
- always 슬롯의 실패는 세션 전체의 실패다. 열려 있던 심볼이 모두 실패로 온다.
- 실패한 세션은 unbind → detached 순서로 정리된다.
- 다음 `update()`가 init·always·bind를 처음부터 다시 한다.

실행
    uv run examples/ex23_always_failure.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex23: ----- 1. BTC, ETH를 하나씩 넣는다 -----
    ex23.portfolio: init {no=1}
    ex23.portfolio: always
    ex23.portfolio: bind {symbol=BTC}
    ex23.portfolio: bind {symbol=ETH}
    ex23.portfolio: unbind {symbol=BTC}
    ex23.portfolio: unbind {symbol=ETH}
    ex23.portfolio: detached {no=1}
    trading_core.domain: 세션 슬롯이 실패했다
      ...
    ConnectionError: 지수 피드가 끊겼다
    ex23: 실패 통지 {symbols=['BTC', 'ETH'], cause=ConnectionError: 지수 피드가 끊겼다}
    ex23: ----- 2. update({'BTC'}): init부터 다시 선다 -----
    ex23.portfolio: init {no=2}
    ex23.portfolio: always
    ex23.portfolio: bind {symbol=BTC}
    ex23: 받은 심볼 {symbols=['BTC', 'INDEX']}
    ex23.portfolio: unbind {symbol=BTC}
    ex23.portfolio: detached {no=2}
    (1단계의 unbind 두 줄은 함께 돌아 순서가 실행마다 바뀐다.)

다음: ex24_symbol_rejected.py — binder가 심볼 하나만 거부할 때
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    Runnable,
    SessionRequest,
    SourceRequest,
    StageFailed,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
FAIL_AT = 3
"""첫 세션의 지수 단계는 이 번째 지수에서 던진다."""

log = get_logger("ex23")
portfolio_log = get_logger("ex23.portfolio")

INITS: list[int] = []
EVENTS: list[str] = []


# ===== binder 쪽 (1): 소스 요청 — 코인 가격과 시장 지수 =====


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


@initialize
def index(req: IndexReq) -> IndexReq:
    return req


@index
async def _(ctx: IndexReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=1000.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 세션 요청 — 첫 세션의 always가 도중에 던진다 =====


class PortfolioReq(SessionRequest):
    pass


class PriceData(DataModel):
    price: float


class PortfolioCtx:
    def __init__(self, no: int) -> None:
        self.no = no


class Index(Runnable[TickData, PriceData]):
    def __init__(self, ctx: PortfolioCtx) -> None:
        self.ctx = ctx
        self.seen = 0

    async def invoke(self, input: TickData) -> PriceData:
        self.seen += 1
        if self.ctx.no == 1 and self.seen == FAIL_AT:
            raise ConnectionError("지수 피드가 끊겼다")
        return PriceData(symbol="INDEX", price=input.price)


class Price(Runnable[TickData, PriceData]):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: TickData) -> PriceData:
        return PriceData(symbol=self.symbol, price=input.price)


@initialize
def portfolio(req: PortfolioReq) -> PortfolioCtx:
    INITS.append(len(INITS) + 1)
    portfolio_log.info("init", no=INITS[-1])
    EVENTS.append("init")
    return PortfolioCtx(INITS[-1])


@portfolio.always
async def _(ctx: PortfolioCtx):
    portfolio_log.info("always")
    EVENTS.append("always")
    yield IndexReq()("CRYPTO10") | Index(ctx)


@portfolio
async def _(ctx: PortfolioCtx, symbol: str):
    portfolio_log.info("bind", symbol=symbol)
    EVENTS.append(f"bind {symbol}")
    yield TickReq()(f"{symbol}/USD") | Price(symbol)


@portfolio.unbind
async def _(ctx: PortfolioCtx, symbol: str):
    portfolio_log.info("unbind", symbol=symbol)
    EVENTS.append(f"unbind {symbol}")


@portfolio.detached
async def _(ctx: PortfolioCtx):
    portfolio_log.info("detached", no=ctx.no)
    EVENTS.append("detached")


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: always 파이프라인이 실패할 때 ━━━━━━━━━━")
    INITS.clear()
    EVENTS.clear()
    failures: list[StageFailed] = []
    received: list[str] = []

    async def collect(data: DataModel) -> None:
        received.append(data.symbol)

    async def on_error(failed: StageFailed) -> None:
        failures.append(failed)
        log.warning("실패 통지", symbols=sorted(failed.symbols), cause=failed.cause)

    async with domain.subscribe(PortfolioReq(), collect, on_error) as sub:
        log.info("----- 1. BTC, ETH를 하나씩 넣는다 -----")
        await sub.update({"BTC"})
        await sub.update({"BTC", "ETH"})
        async with asyncio.timeout(3):
            while not failures:
                await asyncio.sleep(0.05)

        assert failures[0].symbols == {"BTC", "ETH"}  # 열려 있던 심볼 모두
        assert failures[0].cause == "ConnectionError: 지수 피드가 끊겼다"
        assert EVENTS[:4] == ["init", "always", "bind BTC", "bind ETH"]
        assert sorted(EVENTS[4:6]) == ["unbind BTC", "unbind ETH"]  # 둘은 함께 돈다
        assert EVENTS[6:] == ["detached"]

        log.info("----- 2. update({'BTC'}): init부터 다시 선다 -----")
        EVENTS.clear()
        received.clear()
        await sub.update({"BTC"})
        await asyncio.sleep(0.5)
        log.info("받은 심볼", symbols=sorted(set(received)))
        assert EVENTS == ["init", "always", "bind BTC"]
        assert INITS == [1, 2]
        assert set(received) == {"INDEX", "BTC"}

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
