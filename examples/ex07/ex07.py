import re
from asyncio import sleep
from typing import Literal

from pydantic import BaseModel

from trading_core import DataModel, GenerateModel, initialize
from trading_core.model import RequestModel, Runnable

INIT_PRICE_DICT: dict[str, float] = {
    "BTC/USD": 100,
    "ETH/USD": 200,
    "XRP/USD": 300,
    "BTC/KRW": 1000,
    "ETH/KRW": 2000,
    "XRP/KRW": 3000,
}

type QuoteType = Literal["USD", "KRW"]

_SYMBOL_PATTERN = re.compile(r"^([A-Z0-9]+)/([A-Z0-9]+)$")


def base_of(symbol: str) -> str:
    """`"BTC/USD"`처럼 `기초/견적` 형식인 심볼에서 기초 자산(`"BTC"`)만 뽑아낸다."""
    matched = _SYMBOL_PATTERN.match(symbol)
    if matched is None:
        raise ValueError(f"'{symbol}'은(는) '기초/견적' 형식의 심볼이 아니다")
    return matched.group(1)


def quote_of(symbol: str) -> str:
    """`"BTC/USD"`처럼 `기초/견적` 형식인 심볼에서 견적 자산(`"USDT"`)만 뽑아낸다."""
    matched = _SYMBOL_PATTERN.match(symbol)
    if matched is None:
        raise ValueError(f"'{symbol}'은(는) '기초/견적' 형식의 심볼이 아니다")
    return matched.group(2)


class TickReq(GenerateModel): ...


class TickData(DataModel):
    price: float


class TickCtx(BaseModel):
    current_price_dict: dict[str, float]


@initialize
def tick(req: TickReq) -> TickCtx:
    return TickCtx(current_price_dict=INIT_PRICE_DICT.copy())


@tick
async def _(ctx: TickCtx, symbols: set[str]):
    while True:
        for symbol in symbols:
            yield TickData(symbol=symbol, price=ctx.current_price_dict[symbol])
            ctx.current_price_dict[symbol] += 1
            await sleep(0.5)


class SwingReq(RequestModel):
    quote: QuoteType


class SwingData(DataModel):
    quote: QuoteType
    price: float
    swing: float


class SwingCtx(BaseModel):
    quote: QuoteType
    symbols: set[str] = set()


@initialize
def swing(req: SwingReq):
    return SwingCtx(quote=req.quote)


class SwingRunnable(Runnable):
    def __init__(self, quote: QuoteType, symbol: str):
        self.quote: QuoteType = quote
        self.symbol = symbol
        self.active_price = 0

    async def invoke(self, input: TickData) -> SwingData | None:
        if self.active_price == 0:
            self.active_price = input.price
            return
        swing_val = input.price - self.active_price
        self.active_price = input.price
        return SwingData(symbol=self.symbol, quote=self.quote, price=input.price, swing=swing_val)


@swing
async def _(ctx: SwingCtx, symbol: str):
    seq = TickReq()(f"{symbol}/{ctx.quote}") | SwingRunnable(ctx.quote, symbol)
    yield seq
