"""ex14: 단계가 여럿인 파이프라인 — `req(s) | a | b | c`

파이프라인에는 단계를 `|`로 얼마든지 이을 수 있다. 데이터는 왼쪽부터 차례로 지나가고, 앞 단계가
돌려준 값이 다음 단계의 입력이 된다. 어느 단계든 `None`을 돌려주면 그 데이터는 **거기서 멈추고**
뒤 단계는 불리지 않는다.

    TickReq()("BTC/USD") | Normalize("BTC") | EveryOther() | ToKrw(1400)
         TickData            → PriceData       → PriceData    → PriceData(KRW)
                                                  (둘 중 하나는 None)

단계를 잘게 나누면 하나하나가 짧고, 다른 세션에서 다시 쓰기 쉽다. `Runnable[입력, 출력]`으로
입출력 타입을 적어 두면 pyright가 단계 사이의 타입이 맞는지 보는 데도 도움이 된다.

배우는 것
- 단계는 `|`로 잇는다. 단계 수에는 제한이 없다.
- 중간 단계가 `None`을 돌려주면 뒤 단계는 불리지 않는다(`ToKrw`의 호출 수가 `Normalize`의 절반).
- 단계 객체는 bind에서 슬롯마다 만들므로 각 단계의 상태도 심볼별이다.

실행
    uv run examples/ex14_multi_step.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex14: 수신 {symbol=BTC, price=141400.0}
    ex14: 수신 {symbol=BTC, price=144200.0}
    ex14: 수신 {symbol=BTC, price=147000.0}
    ex14: 단계별 호출 수 {normalize=6, every_other=6, to_krw=3}

다음: ex15_two_sources.py — 한 슬롯에 상위 둘을 붙이기
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    Runnable,
    SessionRequest,
    SourceRequest,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.1
KRW_PER_USD = 1400.0

log = get_logger("ex14")

CALLS = {"normalize": 0, "every_other": 0, "to_krw": 0}
"""단계별 `invoke()` 호출 수."""


# ===== binder 쪽 (1): 소스 요청 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=100.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 세션 요청과 단계 셋 =====


class PriceData(DataModel):
    price: float


class Normalize(Runnable[TickData, PriceData]):
    """상위 데이터를 하위 표기의 `PriceData`로 바꾼다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: TickData) -> PriceData:
        CALLS["normalize"] += 1
        return PriceData(symbol=self.symbol, price=input.price)


class EveryOther(Runnable[PriceData, PriceData]):
    """둘 중 하나만 통과시킨다(솎아내기). 나머지는 `None`으로 멈춘다."""

    def __init__(self) -> None:
        self.n = 0

    async def invoke(self, input: PriceData) -> PriceData | None:
        CALLS["every_other"] += 1
        self.n += 1
        return input if self.n % 2 == 0 else None


class ToKrw(Runnable[PriceData, PriceData]):
    def __init__(self, rate: float) -> None:
        self.rate = rate

    async def invoke(self, input: PriceData) -> PriceData:
        CALLS["to_krw"] += 1
        return PriceData(symbol=input.symbol, price=input.price * self.rate)


class KrwEveryOtherReq(SessionRequest):
    pass


@initialize
def krw_every_other(req: KrwEveryOtherReq) -> KrwEveryOtherReq:
    return req


@krw_every_other
async def _(ctx: KrwEveryOtherReq, symbol: str):
    yield TickReq()(f"{symbol}/USD") | Normalize(symbol) | EveryOther() | ToKrw(KRW_PER_USD)


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 단계가 여럿인 파이프라인 ━━━━━━━━━━")
    for key in CALLS:
        CALLS[key] = 0
    received: list[PriceData] = []

    async with domain.stream(KrwEveryOtherReq(), {"BTC"}) as stream:
        async for data in stream:
            item = cast_model(data, PriceData)
            log.info("수신", symbol=item.symbol, price=item.price)
            received.append(item)
            if len(received) == 3:
                break
    log.info(
        "단계별 호출 수",
        normalize=CALLS["normalize"],
        every_other=CALLS["every_other"],
        to_krw=CALLS["to_krw"],
    )

    # 100·101·102·...의 두 번째마다(101, 103, 105)를 원화로.
    assert [item.price for item in received] == [p * KRW_PER_USD for p in (101.0, 103.0, 105.0)]
    # 앞 두 단계는 매번 불렸고, 마지막 단계는 EveryOther가 통과시킨 절반만 받았다.
    # (break한 뒤 구독이 닫히기 전에 틱이 하나 더 지나갈 수 있어 정확한 수 대신 비율을 본다.)
    assert CALLS["every_other"] == CALLS["normalize"]
    assert CALLS["to_krw"] == CALLS["every_other"] // 2
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
