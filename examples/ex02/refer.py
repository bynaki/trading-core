from typing import Literal

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


class NamingContext:
    cxt_dict: dict[str, NamingReq] = {}

    def __init__(self, req: NamingReq) -> None:
        self.content_id = req.get_tr_content_id()
        assert not self.cxt_dict.get(req.get_tr_content_id()), (
            "중복 'content_id' 갖은 객체는 생성할수 없다. 유일해야 한다."
        )
        self.cxt_dict[self.content_id] = req

    @property
    def req_model(self) -> NamingReq:
        return self.cxt_dict[self.content_id]

    def detach(self) -> None:
        del self.cxt_dict[self.content_id]


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
            req = ctx.req_model
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
    print(f"Detached NamingReq - {ctx.req_model.kind}")
    ctx.detach()
