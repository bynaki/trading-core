"""ex09: 요청 필드에 따라 다른 거래소에 붙기

거래소마다 심볼 표기도, 데이터 모양도 다르다.

| 거래소 | 요청 | 심볼 표기 | 데이터 |
| --- | --- | --- | --- |
| 바이낸스(가짜) | `BinanceReq` | `"BTCUSDT"` | `BinanceTrade.p` |
| 업비트(가짜) | `UpbitReq` | `"KRW-BTC"` | `UpbitTrade.trade_price` |

소비자는 이 차이를 몰랐으면 한다. 파생 요청 `PriceReq(quote=...)` 하나로 `"BTC"`를 구독하면
`quote`에 따라 알맞은 거래소에 붙고, 데이터는 같은 `PriceData`로 받는다. `require`가 **요청
필드**(`quote`)를 보고 상위 요청을 고르고, 파생 generator가 같은 필드를 보고 데이터를 되돌린다.

    PriceReq(quote="USD") {"BTC","ETH"} ─→ BinanceReq {"BTCUSDT","ETHUSDT"}
    PriceReq(quote="KRW") {"BTC"}       ─→ UpbitReq   {"KRW-BTC"}

**심볼마다 다른 거래소는 고를 수 없다.** 파생 스테이지는 상위 스테이지 하나만 바라본다. `require`는
심볼 집합 전체를 받아 상위 요청 하나를 돌려줄 뿐이다. "BTC는 바이낸스에서, XRP는 업비트에서"가
필요하면 `quote`가 다른 요청 둘로 나눠 구독하거나, 심볼마다 따로 붙는 세션 요청을 쓴다(ex15).

배우는 것
- `require`는 요청 필드로 상위 요청의 **타입**까지 고를 수 있다. `quote`가 다르면 content_id가
  다르니 파생 스테이지도 따로 선다.
- 파생 generator는 컨텍스트(여기서는 요청)의 같은 필드로 `cast_model()` 대상과 되돌릴 표기를 고른다.
- 상위가 무엇이든 소비자는 같은 데이터 모델을 받는다.

실행
    uv run examples/ex09_choose_upstream.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex09: 거래소별 심볼 {binance=['BTCUSDT', 'ETHUSDT'], upbit=['KRW-BTC']}
    ex09.binance: generator 시작 {symbols=['BTCUSDT', 'ETHUSDT']}
    ex09.upbit: generator 시작 {symbols=['KRW-BTC']}
    ex09: USD 소비자가 받은 첫 가격 {symbol=BTC, price=100.0, quote=USD}
    ex09: KRW 소비자가 받은 첫 가격 {symbol=BTC, price=140000.0, quote=KRW}

다음: ex10_chained.py — 파생 요청 위에 파생 요청
"""

import asyncio
from pathlib import Path
from typing import Literal

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
USD_PRICE = {"BTC": 100.0, "ETH": 200.0}
"""기초 자산별 USD 시작 가격. 업비트는 여기에 KRW_PER_USD를 곱한다."""
KRW_PER_USD = 1400.0

log = get_logger("ex09")
binance_log = get_logger("ex09.binance")
upbit_log = get_logger("ex09.upbit")


# ===== binder 쪽 (1): 소스 요청 둘 — 표기도 데이터 모양도 다르다 =====


class BinanceReq(SourceRequest):
    pass


class BinanceTrade(DataModel):
    p: float
    """USDT 가격. 줄임말 필드를 쓴다."""


@initialize
def binance(req: BinanceReq) -> BinanceReq:
    return req


@binance
async def _(ctx: BinanceReq, symbols: set[str]):
    """`symbols`는 `"BTCUSDT"` 꼴이다."""

    binance_log.info("generator 시작", symbols=sorted(symbols))
    n = 0
    while True:
        for symbol in sorted(symbols):
            base = symbol.removesuffix("USDT")
            yield BinanceTrade(symbol=symbol, p=USD_PRICE[base] + n)
        n += 1
        await asyncio.sleep(INTERVAL)


class UpbitReq(SourceRequest):
    pass


class UpbitTrade(DataModel):
    trade_price: float
    """KRW 가격."""


@initialize
def upbit(req: UpbitReq) -> UpbitReq:
    return req


@upbit
async def _(ctx: UpbitReq, symbols: set[str]):
    """`symbols`는 `"KRW-BTC"` 꼴이다."""

    upbit_log.info("generator 시작", symbols=sorted(symbols))
    n = 0
    while True:
        for symbol in sorted(symbols):
            base = symbol.removeprefix("KRW-")
            yield UpbitTrade(symbol=symbol, trade_price=(USD_PRICE[base] + n) * KRW_PER_USD)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 파생 요청 — quote로 거래소를 고른다 =====


class PriceReq(DerivedRequest):
    quote: Literal["USD", "KRW"]


class PriceData(DataModel):
    """거래소와 상관없이 소비자가 받는 하나의 모양."""

    price: float
    quote: str


@PriceReq.require
def _(req: PriceReq, symbols: set[str]) -> tuple[BinanceReq | UpbitReq, set[str]]:
    """요청 필드로 상위 요청을 고르고, 그 거래소의 표기로 심볼을 바꾼다."""

    if req.quote == "USD":
        return BinanceReq(), {f"{s}USDT" for s in symbols}
    return UpbitReq(), {f"KRW-{s}" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    """require가 고른 것과 같은 기준(`ctx.quote`)으로 데이터를 좁히고 표기를 되돌린다."""

    while True:
        data = await recv()
        if ctx.quote == "USD":
            trade = cast_model(data, BinanceTrade)
            yield PriceData(symbol=trade.symbol.removesuffix("USDT"), price=trade.p, quote="USD")
        else:
            upbit_trade = cast_model(data, UpbitTrade)
            yield PriceData(
                symbol=upbit_trade.symbol.removeprefix("KRW-"),
                price=upbit_trade.trade_price,
                quote="KRW",
            )


# ===== 소비자 쪽 =====


class Recorder:
    def __init__(self) -> None:
        self.items: list[PriceData] = []

    async def __call__(self, data: DataModel) -> None:
        self.items.append(cast_model(data, PriceData))


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 요청 필드에 따라 다른 거래소에 붙기 ━━━━━━━━━━")
    usd, krw = Recorder(), Recorder()

    async with (
        domain.subscribe(PriceReq(quote="USD"), usd) as sub_usd,
        domain.subscribe(PriceReq(quote="KRW"), krw) as sub_krw,
    ):
        await sub_usd.update({"BTC", "ETH"})
        await sub_krw.update({"BTC"})
        on_binance = domain.get_shared_symbols(BinanceReq().tr_content_id)
        on_upbit = domain.get_shared_symbols(UpbitReq().tr_content_id)
        log.info("거래소별 심볼", binance=sorted(on_binance), upbit=sorted(on_upbit))
        await asyncio.sleep(0.5)

    first_usd, first_krw = usd.items[0], krw.items[0]
    log.info(
        "USD 소비자가 받은 첫 가격", **first_usd.model_dump(include={"symbol", "price", "quote"})
    )
    log.info(
        "KRW 소비자가 받은 첫 가격", **first_krw.model_dump(include={"symbol", "price", "quote"})
    )

    assert on_binance == {"BTCUSDT", "ETHUSDT"}
    assert on_upbit == {"KRW-BTC"}
    # 소비자는 거래소 표기를 보지 않는다.
    assert {item.symbol for item in usd.items} == {"BTC", "ETH"}
    assert {item.symbol for item in krw.items} == {"BTC"}
    assert first_usd.price == USD_PRICE["BTC"]
    assert first_krw.price == USD_PRICE["BTC"] * KRW_PER_USD
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
