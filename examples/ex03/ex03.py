from asyncio import sleep
from collections.abc import Set
from typing import Literal

from trading_core import DataModel, Receiver, RequestModel, generator


class PriceReq(RequestModel):
    ohlc: Literal["open", "high", "low", "close"]


class PriceData(DataModel):
    price: int


class PriceContext:
    def __init__(self, quantity: int) -> None:
        self._quantity = quantity
        self._count_dict: dict[str, int] = {}

    def price(self, symbol: str) -> int:
        if not self._count_dict.get(symbol):
            self._count_dict[symbol] = 0
        self._count_dict[symbol] += 1
        return self._count_dict[symbol] * self._quantity


@generator(PriceReq)
def price(req: PriceReq):
    quantity = 0
    if req.ohlc == "open":
        quantity = 10
    elif req.ohlc == "high":
        quantity = 1000
    elif req.ohlc == "low":
        quantity = 1
    elif req.ohlc == "close":
        quantity = 100
    return PriceContext(quantity)


@price.bind
async def _(ctx: PriceContext, symbols: Set[str], recv: Receiver | None):
    for symbol in symbols:
        yield PriceData(symbol=symbol, price=ctx.price(symbol))
        await sleep(1)
