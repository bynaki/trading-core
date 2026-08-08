"""공통 이름 원천을 요구하고 한 종류의 이름만 선택하는 파생 예제."""

from typing import Literal

from trading_core import (
    ClosedConnection,
    DataModel,
    DependentModel,
    Receiver,
    cast_model,
    initialize,
)

if __package__:
    from . import origin
else:
    import origin


class NamingReq(DependentModel):
    """원천 데이터에서 선택할 이름 종류를 지정하는 파생 요청."""

    kind: Literal["flower", "dog", "cat"]


@NamingReq.require
def naming_requirement(req: NamingReq) -> origin.NamingAllReq:
    """모든 파생 요청을 필드 없는 동일한 원천 요청에 연결한다."""

    return origin.NamingAllReq()


class NamingData(DataModel):
    """원천에서 선택한 이름 하나를 담는 파생 출력 모델."""

    name: str


class NamingContext:
    """같은 kind 요청이 공유하는 파생 스테이지 컨텍스트."""

    cxt_dict: dict[str, NamingReq] = {}

    def __init__(self, req: NamingReq) -> None:
        self.content_id = req.get_tr_content_id()
        assert not self.cxt_dict.get(req.get_tr_content_id()), (
            "중복 'content_id' 갖은 객체는 생성되지 않는다. 유일하다."
        )
        self.cxt_dict[self.content_id] = req
        self.count = 0

    @property
    def req_model(self) -> NamingReq:
        """content ID에 연결된 파생 요청을 반환한다."""

        return self.cxt_dict[self.content_id]

    def detach(self) -> None:
        """파생 스테이지 종료 시 클래스 수준 저장소에서 요청을 제거한다."""

        del self.cxt_dict[self.content_id]


@initialize
def naming(req: NamingReq) -> NamingContext:
    """파생 요청의 공유 컨텍스트를 만든다."""

    return NamingContext(req=req)


@naming
async def _(ctx: NamingContext, symbols: set[str], recv: Receiver):
    """원천 데이터를 수신하여 요청한 종류의 이름만 발행한다."""

    ctx.count += 1
    print(f"!!!!!!! {ctx.count} Updating Naming Stage - req: {ctx.req_model.kind}")
    try:
        while data := await recv():
            d = cast_model(data, origin.NamingAllData)
            if d.symbol not in symbols:
                print(f"warning: 요청한 심볼과 받은 심볼이 일치하지 않는다. - {d.symbol}")
            req = ctx.req_model
            if req.kind == "flower":
                yield NamingData(symbol=d.symbol, name=f"{d.flower} - flower")
            elif req.kind == "dog":
                yield NamingData(symbol=d.symbol, name=f"{d.dog} - dog")
            elif req.kind == "cat":
                yield NamingData(symbol=d.symbol, name=f"{d.cat} - cat")
            else:
                raise Exception("있을수 없는일!!")
    except ClosedConnection as e:
        print(f"Closed Receiver at NamingReq Binder - {e}")


@naming.detached
async def _(ctx: NamingContext):
    """마지막 파생 구독이 사라지면 공유 컨텍스트를 분리한다."""

    print(f"******* Detached Naming Stage - req: {ctx.req_model.kind}")
    ctx.detach()
