"""같은 파생 요청을 서로 다른 심볼 집합으로 **동시에** 구독하는 예제.

ex04와 같은 구조(기초 자산 → 거래소 표기로 심볼을 변환하는 `require`)를 최소한으로
줄였다. 다른 점은 소비 방식뿐이다. ex04의 `run_ex.py`는 요청을 순차로 실행하지만
여기서는 두 소비자가 같은 `PriceRequest(quote="usd")`를 서로 다른 심볼로 동시에
구독한다.

보여 주는 불변식은 하나다. **파생 스테이지가 상위 원천에 등록하는 심볼은 구독자
전체의 합집합이어야 한다.** 각 콜백은 자신이 어떤 심볼로 (재)시작했는지 출력하므로,
`[DEPENDENT]` 줄과 `[ORIGIN]` 줄의 심볼을 비교하면 두 계층의 구독 상태가 맞물려
있는지 눈으로 확인할 수 있다. 이 불변식이 깨져 있던 시절에는 먼저 구독한 쪽이 아무
오류 없이 데이터만 끊겼다 — 자세한 내력은 `README.md`에 있다.
"""

from asyncio import sleep
from typing import Literal

from trading_core import DataModel, DependentModel, GenerateModel, initialize
from trading_core.model import Receiver, cast_model

QUOTE_SUFFIX = "/USD"

# 상위(거래소) 심볼 공간의 기준 가격. 여기 없는 심볼을 구독하면 즉시 드러나도록 둔다.
BASE_PRICE: dict[str, float] = {
    "BTC/USD": 68_000.0,
    "ETH/USD": 3_200.0,
    "SOL/USD": 145.0,
}


def base_of(symbol: str) -> str:
    """`"BTC/USD"`에서 기초 자산(`"BTC"`)만 뽑아낸다."""

    if not symbol.endswith(QUOTE_SUFFIX):
        raise ValueError(f"'{symbol}'은(는) '{QUOTE_SUFFIX}' 표기가 아니다")
    return symbol[: -len(QUOTE_SUFFIX)]


class TickRequest(GenerateModel):
    """거래소 표기 심볼로 체결가를 요청하는 원천 요청."""

    venue: Literal["mockex"]


class TickData(DataModel):
    """원천이 발행하는 체결가. `symbol`은 `"BTC/USD"`처럼 거래소 표기다."""

    price: float
    seq: int


@initialize
def tick(req: TickRequest) -> TickRequest:
    """요청 자체를 원천 스테이지의 공유 컨텍스트로 사용한다."""

    return req


@tick
async def _(ctx: TickRequest, symbols: set[str]):
    """구독 심볼 전체를 한 바퀴 돌며 0.5초 간격으로 체결가를 발행한다.

    **이 콜백이 받은 `symbols`가 곧 상위 원천의 실제 구독 상태다.** 파생 스테이지가
    갱신될 때마다 generator가 재시작되므로, 로그의 `[ORIGIN]` 줄을 보면 상위에 어떤
    심볼이 등록되었는지 그대로 확인할 수 있다.
    """

    print(f"[ORIGIN]    generator (재)시작 — 상위 구독 심볼 = {sorted(symbols)}")
    seq = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + seq, seq=seq)
        seq += 1
        await sleep(0.5)


class PriceRequest(DependentModel):
    """기초 자산 심볼만 받아 체결가를 돌려주는 파생 요청."""

    quote: Literal["usd"]


class PriceData(DataModel):
    """소비자에게 전달되는 체결가. `symbol`은 `"BTC"`처럼 기초 자산이다."""

    price: float
    seq: int


@PriceRequest.require
def price_requirement(req: PriceRequest, symbols: set[str]):
    """하위 심볼(`BTC`)을 상위 거래소 표기(`BTC/USD`)로 바꾼다.

    상위 요청 자체는 심볼과 무관하게 항상 같다. 즉 이 파생 스테이지는 언제나 하나의
    원천 스테이지만 바라본다 — 문제는 그 원천에 **몇 개의 심볼을 등록하느냐**다.
    """

    upstream = {f"{s}{QUOTE_SUFFIX}" for s in symbols}
    print(f"[REQUIRE]   하위 {sorted(symbols)} -> 상위 {sorted(upstream)}")
    return TickRequest(venue="mockex"), upstream


@initialize
def price(req: PriceRequest) -> PriceRequest:
    """요청 자체를 파생 스테이지의 공유 컨텍스트로 사용한다."""

    return req


@price
async def _(ctx: PriceRequest, symbols: set[str], recv: Receiver):
    """상위 체결가를 받아 심볼을 기초 자산으로 되돌려 발행한다.

    `symbols`는 파생 스테이지 구독자들의 **합집합**이다. `[DEPENDENT]` 줄과
    `[ORIGIN]` 줄의 심볼을 비교해 보면 두 계층의 구독 상태가 맞물려 있는 것이 보인다.
    """

    print(f"[DEPENDENT] generator (재)시작 — 하위 구독 심볼 = {sorted(symbols)}")
    while True:
        data = await recv()
        tick_data = cast_model(data, TickData)
        symbol = base_of(tick_data.symbol)
        if symbol not in symbols:
            print(f"warning: 구독하지 않은 심볼이 올라왔다. - {symbol}, {sorted(symbols)}")
            continue
        yield PriceData(symbol=symbol, price=tick_data.price, seq=tick_data.seq)
