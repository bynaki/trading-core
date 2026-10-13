"""ex07: 다른 요청의 데이터를 받아 가공하는 파생 요청

거래소 체결가(USD)를 원화·엔화로 바꿔 보고 싶다고 하자. 환율마다 거래소에 따로 접속할 이유는 없다.
체결가는 소스 요청 하나로 받고, 그 데이터를 받아 가공하는 요청을 따로 둔다. 이것이 **파생 요청**
(`DerivedRequest`)이다.

    소비자 A ── ConvertReq(KRW) ─┐
                                 ├─→ TickReq(mock)   ← 소스 스테이지 하나를 나눠 쓴다
    소비자 B ── ConvertReq(JPY) ─┘

파생 요청은 세 가지를 정한다.

1. **무엇에 기대는가**: `@ConvertReq.require`로 상위 요청을 돌려준다. 소비자는 상위 요청을 몰라도
   된다. `Domain`이 상위 스테이지를 세우고 이어 준다.
2. **컨텍스트**: 소스 요청처럼 `@initialize`로 init 콜백을 등록한다.
3. **가공**: generate 콜백이 인자 하나를 더 받는다. `recv()`를 await하면 상위 데이터가 한 건씩 온다.

배우는 것
- `require` 콜백은 요청만 받아 상위 요청을 돌려준다. 심볼은 그대로 상위에 넘어간다.
- 파생 generate 콜백은 `(ctx, symbols, recv)`를 받는다. `recv()`로 받은 데이터는 `cast_model()`로
  좁힌다.
- 내용이 다른 파생 요청 둘(KRW·JPY)은 파생 스테이지가 따로지만, 상위 요청이 같으므로 소스 스테이지는
  하나를 나눠 쓴다(init 한 번).
- 소스 스테이지가 받는 심볼은 파생 스테이지들이 등록한 심볼의 합집합이다.

실행
    uv run examples/ex07_derived.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex07.convert: init {currency=KRW}
    ex07.tick: init {exchange=mock}
    ex07.convert: init {currency=JPY}
    ex07: 소스 스테이지가 돌리는 심볼 {shared=['BTC', 'ETH']}
    ex07.convert: generator 시작 {currency=KRW, symbols=['BTC']}
    ex07.convert: generator 시작 {currency=JPY, symbols=['BTC', 'ETH']}
    ex07: A가 받은 첫 가격 {symbol=BTC, price=140000.0, currency=KRW}
    ex07: B가 받은 첫 가격 {symbol=BTC, price=15000.0, currency=JPY}

다음: ex08_mapped_symbols.py — 상위가 심볼을 다르게 부를 때
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
BASE_PRICE = {"BTC": 100.0, "ETH": 200.0}
RATE = {"KRW": 1400.0, "JPY": 150.0}
"""USD 1에 대한 환율."""

log = get_logger("ex07")
tick_log = get_logger("ex07.tick")
convert_log = get_logger("ex07.convert")

TICK_INITS: list[str] = []
"""소스 스테이지 init이 불린 거래소."""


# ===== binder 쪽 (1): 소스 요청 — 체결가(USD) =====


class TickReq(SourceRequest):
    exchange: str


class TickData(DataModel):
    price: float
    """USD 가격."""


@initialize
def tick(req: TickReq) -> TickReq:
    tick_log.info("init", exchange=req.exchange)
    TICK_INITS.append(req.exchange)
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 파생 요청 — 환산 가격 =====


class ConvertReq(DerivedRequest):
    """체결가를 `currency`로 환산해 달라는 요청."""

    currency: Literal["KRW", "JPY"]


class ConvertedData(DataModel):
    price: float
    currency: str


@ConvertReq.require
def _(req: ConvertReq) -> TickReq:
    """상위 요청을 정한다. 요청만 받는 형태라 소비자의 심볼이 그대로 상위에 넘어간다.

    어떤 통화든 같은 `TickReq(exchange="mock")`을 돌려주므로 상위 소스 스테이지는 하나다.
    """

    return TickReq(exchange="mock")


@initialize
def convert(req: ConvertReq) -> ConvertReq:
    """파생 요청의 init 콜백. 소스 요청과 똑같이 등록한다."""

    convert_log.info("init", currency=req.currency)
    return req


@convert
async def _(ctx: ConvertReq, symbols: set[str], recv: Receiver):
    """파생 generate 콜백. 세 번째 인자 `recv`로 상위 데이터를 받는다.

    `recv()`는 상위 데이터가 올 때까지 기다린다. 받은 데이터는 `DataModel` 타입이므로
    `cast_model()`로 상위의 실제 타입으로 좁혀 쓴다.
    """

    convert_log.info("generator 시작", currency=ctx.currency, symbols=sorted(symbols))
    rate = RATE[ctx.currency]
    while True:
        tick = cast_model(await recv(), TickData)
        yield ConvertedData(symbol=tick.symbol, price=tick.price * rate, currency=ctx.currency)


# ===== 소비자 쪽 =====


class Recorder:
    """받은 환산 가격을 모으는 Sender."""

    def __init__(self) -> None:
        self.items: list[ConvertedData] = []

    async def __call__(self, data: DataModel) -> None:
        self.items.append(cast_model(data, ConvertedData))


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 다른 요청의 데이터를 받아 가공하는 파생 요청 ━━━━━━━━━━")
    TICK_INITS.clear()
    a, b = Recorder(), Recorder()

    # 소비자는 파생 요청만 안다. 상위 TickReq는 `Domain`이 require를 보고 세운다.
    async with (
        domain.subscribe(ConvertReq(currency="KRW"), a) as sub_a,
        domain.subscribe(ConvertReq(currency="JPY"), b) as sub_b,
    ):
        await sub_a.update({"BTC"})
        await sub_b.update({"BTC", "ETH"})  # B의 파생 스테이지도 같은 소스 스테이지에 붙는다
        shared = domain.get_shared_symbols(TickReq(exchange="mock").tr_content_id)
        log.info("소스 스테이지가 돌리는 심볼", shared=sorted(shared))
        await asyncio.sleep(0.5)

    first_a, first_b = a.items[0], b.items[0]
    log.info("A가 받은 첫 가격", **first_a.model_dump(include={"symbol", "price", "currency"}))
    log.info("B가 받은 첫 가격", **first_b.model_dump(include={"symbol", "price", "currency"}))

    assert TICK_INITS == ["mock"]  # 파생 스테이지는 둘, 소스 스테이지는 하나
    assert shared == {"BTC", "ETH"}  # A의 {BTC}와 B의 {BTC, ETH}의 합집합
    assert {item.symbol for item in a.items} == {"BTC"}
    assert {item.symbol for item in b.items} == {"BTC", "ETH"}
    assert all(item.currency == "KRW" for item in a.items)
    assert first_a.price == BASE_PRICE["BTC"] * RATE["KRW"]
    assert first_b.price == BASE_PRICE["BTC"] * RATE["JPY"]
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
