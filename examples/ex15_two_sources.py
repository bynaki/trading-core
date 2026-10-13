"""ex15: 한 슬롯에 상위 둘을 붙이기 — 거래소 간 가격 차이

bind 콜백은 파이프라인을 **여러 개** yield할 수 있다. 그러면 그 심볼의 슬롯 하나가 상위 여럿에
붙는다. 두 거래소의 같은 코인 가격을 나란히 보고 차이(스프레드)를 내는 일이 그렇다.

    슬롯 BTC ─┬─ TickReq(exchange="A")("BTC/USD") | Side(book, "a") ─┐
              └─ TickReq(exchange="B")("BTC-USD") | Side(book, "b") ─┴→ SpreadData("BTC")

두 파이프라인의 단계가 같은 `Book` 객체를 나눠 들고, 양쪽 가격이 다 모이면 스프레드를 낸다.
한 슬롯의 데이터는 **한 번에 하나씩** 처리되므로(슬롯마다 큐 하나, 태스크 하나) 두 단계가 같은
객체를 고쳐도 락이 필요 없다.

파이프라인마다 상위 요청과 표기가 달라도 된다. 거래소 A는 `"BTC/USD"`, B는 `"BTC-USD"`라고 부른다.

배우는 것
- bind가 파이프라인을 여럿 yield하면 한 슬롯이 상위 여럿에 붙는다.
- 같은 슬롯의 단계끼리는 bind 안에서 만든 객체로 상태를 나눌 수 있다.
- 심볼이 빠지면 그 슬롯이 붙었던 상위 모두에서 그 심볼이 빠진다. unbind는 심볼마다 한 번이다.

실행
    uv run examples/ex15_two_sources.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex15: ----- 1. update({'BTC'}) -----
    ex15.spread: bind {symbol=BTC}
    ex15: 거래소별 심볼 {a=['BTC/USD'], b=['BTC-USD']}
    ex15: ----- 2. update({'BTC', 'ETH'}) -----
    ex15.spread: bind {symbol=ETH}
    ex15: 거래소별 심볼 {a=['BTC/USD', 'ETH/USD'], b=['BTC-USD', 'ETH-USD']}
    ex15: ----- 3. update({'ETH'}) -----
    ex15.spread: unbind {symbol=BTC}
    ex15: 거래소별 심볼 {a=['ETH/USD'], b=['ETH-USD']}
    ex15.spread: unbind {symbol=ETH}
    ex15: 심볼별 스프레드 {BTC=[0.5], ETH=[1.0]}

다음: ex16_always.py — 구독 심볼과 상관없이 늘 붙는 파이프라인
"""

import asyncio
from pathlib import Path
from typing import Literal

from trading_core import (
    DataModel,
    Domain,
    Runnable,
    SessionRequest,
    SourceRequest,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
PRICE = {
    "A": {"BTC/USD": 100.0, "ETH/USD": 200.0},
    "B": {"BTC-USD": 100.5, "ETH-USD": 201.0},
}
"""거래소별 가격. 표기가 다르다. 스프레드가 늘 같도록 가격은 움직이지 않는다."""

log = get_logger("ex15")
spread_log = get_logger("ex15.spread")


# ===== binder 쪽 (1): 소스 요청 — 거래소 둘 =====


class TickReq(SourceRequest):
    exchange: Literal["A", "B"]


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=PRICE[ctx.exchange][symbol])
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 세션 요청 — 두 거래소의 가격 차이 =====


class SpreadReq(SessionRequest):
    pass


class SpreadData(DataModel):
    a: float
    b: float
    spread: float
    """b - a."""


class Book:
    """한 심볼의 양쪽 가격. 슬롯의 두 단계가 나눠 든다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.price: dict[str, float] = {}


class Side(Runnable[TickData, SpreadData]):
    """한쪽 거래소의 가격을 `Book`에 적고, 양쪽이 다 있으면 스프레드를 낸다."""

    def __init__(self, book: Book, side: Literal["a", "b"]) -> None:
        self.book = book
        self.side = side

    async def invoke(self, input: TickData) -> SpreadData | None:
        self.book.price[self.side] = input.price
        if len(self.book.price) < 2:
            return None  # 아직 한쪽만 왔다
        a, b = self.book.price["a"], self.book.price["b"]
        return SpreadData(symbol=self.book.symbol, a=a, b=b, spread=b - a)


@initialize
def spread(req: SpreadReq) -> SpreadReq:
    return req


@spread
async def _(ctx: SpreadReq, symbol: str):
    """파이프라인 둘을 yield한다. 둘 다 이 심볼의 슬롯 하나에 들어간다."""

    spread_log.info("bind", symbol=symbol)
    book = Book(symbol)
    yield TickReq(exchange="A")(f"{symbol}/USD") | Side(book, "a")
    yield TickReq(exchange="B")(f"{symbol}-USD") | Side(book, "b")


@spread.unbind
async def _(ctx: SpreadReq, symbol: str):
    spread_log.info("unbind", symbol=symbol)


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 한 슬롯에 상위 둘을 붙이기 ━━━━━━━━━━")
    spreads: dict[str, set[float]] = {}

    async def collect(data: DataModel) -> None:
        item = cast_model(data, SpreadData)
        spreads.setdefault(item.symbol, set()).add(item.spread)

    def on_exchanges() -> tuple[set[str], set[str]]:
        a = domain.get_shared_symbols(TickReq(exchange="A").tr_content_id)
        b = domain.get_shared_symbols(TickReq(exchange="B").tr_content_id)
        log.info("거래소별 심볼", a=sorted(a), b=sorted(b))
        return a, b

    async with domain.subscribe(SpreadReq(), collect) as sub:
        log.info("----- 1. update({'BTC'}) -----")
        await sub.update({"BTC"})
        assert on_exchanges() == ({"BTC/USD"}, {"BTC-USD"})
        await asyncio.sleep(0.5)

        log.info("----- 2. update({'BTC', 'ETH'}) -----")
        await sub.update({"BTC", "ETH"})
        assert on_exchanges() == ({"BTC/USD", "ETH/USD"}, {"BTC-USD", "ETH-USD"})
        await asyncio.sleep(0.5)

        log.info("----- 3. update({'ETH'}) -----")
        await sub.update({"ETH"})
        assert on_exchanges() == ({"ETH/USD"}, {"ETH-USD"})  # 양쪽 거래소에서 함께 빠졌다
        await asyncio.sleep(0.3)

    log.info("심볼별 스프레드", BTC=sorted(spreads["BTC"]), ETH=sorted(spreads["ETH"]))
    assert spreads == {"BTC": {0.5}, "ETH": {1.0}}
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
