from typing import Literal, TypedDict

from trading_core import ClosedConnection, DataModel, Receiver, RequestModel, cast_model, generator

from . import origin


class NamingReq(RequestModel):
    kind: Literal["flower", "dog", "cat"]
    count: int


@NamingReq.require(origin.NamingAllReq)
def _(req: NamingReq):
    return origin.NamingAllReq(count=req.count)


class NamingData(DataModel):
    name: str
    count: int


class NamingContext(TypedDict):
    req: NamingReq


@generator(NamingReq)
def naming(req: NamingReq) -> NamingContext:
    return NamingContext(req=req)


@naming.bind
async def _(ctx: NamingContext, symbols: set[str], recv: Receiver | None):
    if recv is None:
        raise Exception("'Receiver'가 있어야 한다.")
    try:
        while data := await recv():
            d = cast_model(data, origin.NamingAllData)
            if d.symbol not in symbols:
                print(f"warning: 요청한 심볼과 받은 심볼이 일치하지 않는다. - {d.symbol}")
            req = ctx["req"]
            if req.kind == "flower":
                yield NamingData(symbol=d.symbol, name=d.flower, count=d.count)
            elif req.kind == "dog":
                yield NamingData(symbol=d.symbol, name=d.dog, count=d.count)
            elif req.kind == "cat":
                yield NamingData(symbol=d.symbol, name=d.cat, count=d.count)
            else:
                raise Exception("있을수 없는일!!")
    except ClosedConnection as e:
        print(f"Closed Receiver at NamingReq Binder - {e}")


@naming.close
async def _(ctx: NamingContext):
    print(f"Closed NamingReq - {ctx['req'].kind}")
