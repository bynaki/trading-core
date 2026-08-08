from typing import Literal

from trading_core import (
    DataModel,
    Receiver,
    initialize,
)
from trading_core.model import DependentModel, GenerateModel


class BinanceRequest(GenerateModel):
    interval: Literal["1m", "5m", "1h"]


class BinanceData(DataModel):
    op: float
    hi: float
    lo: float
    cl: float
    vol: float


class UpbitRequest(GenerateModel):
    interval: Literal["5m", "30m", "1h"]


class OHLCData(DataModel):
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCRequest(DependentModel):
    quote: Literal["usd", "krw"]
    interval: Literal["5m", "1h"]


@OHLCRequest.require
def gen(req: OHLCRequest):
    if req.quote == "usd":
        return BinanceRequest(interval=req.interval)
    elif req.quote == "krw":
        return UpbitRequest(interval=req.interval)
    else:
        raise Exception("Unthinkable!!")


@initialize
def ohlc(req: OHLCRequest) -> OHLCRequest:
    return req


@ohlc
async def binder(ctx: OHLCRequest, symbols: set[str], recv: Receiver):
    while True:
        yield DataModel()
