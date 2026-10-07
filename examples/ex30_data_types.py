"""ex30: 요청 하나, 데이터 여러 종류 — `match`로 가르기

지금까지의 예제는 요청 하나가 데이터 한 종류만 주었다. 그래서 `cast_model(data, TickData)`로
좁히면 됐다. 하지만 요청과 데이터 타입은 1:1이 아니다. 거래소 피드 하나가 체결(`Trade`)과
호가(`Quote`)를 섞어 보내듯, 무엇을 어떤 모양으로 줄지는 **binder가 정한다**. 요청 클래스는 데이터
타입을 선언하지 않고, `stream()`이 주는 데이터의 타입은 언제나 `DataModel`이다.

종류가 여럿이면 `match`(또는 `isinstance`)로 가른다.

    match data:
        case Trade(price=price, qty=qty): ...
        case Quote(bid=bid, ask=ask): ...
        case _: ...                       # binder가 새 종류를 보내기 시작해도 놓치지 않는다

`case Trade(...)` 안에서는 pyright도 `data`를 `Trade`로 좁힌다. pydantic 모델은 위치 패턴
(`Trade(p, q)`)을 지원하지 않으니 키워드 패턴(`price=price`)을 쓴다.

배우는 것
- 요청 하나의 binder가 여러 `DataModel` 하위 클래스를 섞어 `yield`할 수 있다.
- 받는 쪽은 `match`의 클래스 패턴으로 종류를 가르고 필드를 꺼낸다.
- `cast_model()`은 종류가 하나로 정해졌을 때 쓴다. 다른 종류가 오면 `ModelValidationError`다.

실행
    uv run examples/ex30_data_types.py

기대 출력 (줄 앞의 레벨은 뺐다)
    ex30: ━━━━━━━━━━ 시작: 요청 하나, 데이터 여러 종류 ━━━━━━━━━━
    ex30: ----- 1. match로 가른다 -----
    ex30: 호가 {symbol=BTC, bid=99.5, ask=100.5}
    ex30: 호가 {symbol=BTC, bid=100.5, ask=101.5}
    ex30: 체결 {symbol=BTC, price=101.0, qty=1}
    ex30: 호가 {symbol=BTC, bid=101.5, ask=102.5}
    ex30: 호가 {symbol=BTC, bid=102.5, ask=103.5}
    ex30: 체결 {symbol=BTC, price=103.0, qty=3}
    ex30: 받은 수 {quotes=4, trades=2, unknown=0}
    ex30: ----- 2. cast_model()은 한 종류만 -----
    ex30: 호가를 체결로 좁힐 수 없다 {error=ModelValidationError}
    ex30: ━━━━━━━━━━ 끝 ━━━━━━━━━━

알아둘 점
- 클래스 패턴은 `isinstance`라 하위 클래스도 걸린다. `class BlockTrade(Trade)`가 있다면
  `case BlockTrade()`를 `case Trade()`보다 위에 둔다. `cast_model()`은 반대로 model_id가 정확히
  같아야 해서 하위 클래스로도 좁히지 않는다.
- 파생 binder가 `recv()`로 받는 상위 데이터도 마찬가지로 `DataModel`이다. 상위가 여러 종류를
  보내면 파생 binder 안에서도 `match`로 가른다.
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    ModelValidationError,
    SourceRequest,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
TAKE = 6
"""받고 끝낼 데이터 수."""

log = get_logger("ex30")


# ===== binder 쪽: 체결과 호가를 섞어 보내는 피드 =====


class MarketReq(SourceRequest):
    exchange: str


class Trade(DataModel):
    """체결 한 건."""

    price: float
    qty: int


class Quote(DataModel):
    """최우선 호가."""

    bid: float
    ask: float


@initialize
def market(req: MarketReq) -> MarketReq:
    return req


@market
async def _(ctx: MarketReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            mid = 100.0 + n
            yield Quote(symbol=symbol, bid=mid - 0.5, ask=mid + 0.5)  # 호가는 바퀴마다
            if n % 2 == 1:
                yield Trade(symbol=symbol, price=mid, qty=n)  # 체결은 두 바퀴에 한 번
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 요청 하나, 데이터 여러 종류 ━━━━━━━━━━")

    log.info("----- 1. match로 가른다 -----")
    quotes: list[Quote] = []
    trades: list[Trade] = []
    unknown = 0
    async with domain.stream(MarketReq(exchange="mock"), {"BTC"}) as stream:
        async for data in stream:  # data는 DataModel
            match data:
                case Trade(price=price, qty=qty):  # 여기서 data는 Trade
                    log.info("체결", symbol=data.symbol, price=price, qty=qty)
                    trades.append(data)
                case Quote(bid=bid, ask=ask):
                    log.info("호가", symbol=data.symbol, bid=bid, ask=ask)
                    quotes.append(data)
                case _:
                    log.warning("모르는 데이터", type=type(data).__name__)
                    unknown += 1
            if len(quotes) + len(trades) + unknown == TAKE:
                break
    log.info("받은 수", quotes=len(quotes), trades=len(trades), unknown=unknown)
    assert (len(quotes), len(trades), unknown) == (4, 2, 0)

    log.info("----- 2. cast_model()은 한 종류만 -----")
    try:
        cast_model(quotes[0], Trade)
    except ModelValidationError as exc:
        log.warning("호가를 체결로 좁힐 수 없다", error=type(exc).__name__)
    else:
        raise AssertionError("Quote가 Trade로 좁혀지면 안 된다")
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
