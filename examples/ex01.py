from asyncio import sleep

from trading_core import (
    DataModel,
    RequestModel,
    generator,
)
from trading_core.model import Receiver


class CountReq(RequestModel):
    start: int


class CountModel(DataModel):
    count: int


@generator(CountReq)
def gen01(req: CountReq) -> CountReq:
    return req


@gen01.bind
async def _(req: CountReq, symbols: set[str], recv: Receiver | None):
    sym_list = list(symbols)
    count = req.start
    try:
        while True:
            count += 1
            remainder = count % len(sym_list)
            yield CountModel(symbol=sym_list[remainder], count=count)
            await sleep(1)
    finally:
        print(f"Must resource cleaned up - count: {count}")
