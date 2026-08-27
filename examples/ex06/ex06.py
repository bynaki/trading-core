"""합집합이 바뀔 때만 파생 스테이지가 재시작하는 것을 보여 주는 예제.

ex05가 "상위에 **무엇을** 등록하는가"(합집합)를 다뤘다면, 여기서는 "**언제** 다시
시작하는가"를 다룬다. 확인하는 규칙은 하나다.

    구독 심볼의 합집합이 그대로면 generator를 재시작하지 않는다.

이미 합집합에 들어 있는 심볼로 구독자가 하나 더 붙는 경우가 그렇다. 새 구독자는
`SendRouter`에 등록되어 곧바로 데이터를 받지만, 상위 원천도 파생 generator도
그대로 돌아간다. 반대로 합집합이 넓어지거나 좁아지면 두 계층이 함께 재시작한다.

각 generator는 자신이 몇 회차로 (재)시작했는지 출력하고 `GEN_STARTS`에 기록한다.
`run_ex.py`가 단계별 증가분을 세어 재시작 여부를 판정한다.
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
}

# generator가 (재)시작한 누적 횟수. `run_ex.py`가 단계 전후로 읽어 증가분을 낸다.
GEN_STARTS: dict[str, int] = {"origin": 0, "dependent": 0}


def base_of(symbol: str) -> str:
    """`"BTC/USD"`에서 기초 자산(`"BTC"`)만 뽑아낸다."""

    if not symbol.endswith(QUOTE_SUFFIX):
        raise ValueError(f"'{symbol}'은(는) '{QUOTE_SUFFIX}' 표기가 아니다")
    return symbol[: -len(QUOTE_SUFFIX)]


class FeedRequest(GenerateModel):
    """거래소 표기 심볼로 체결가를 요청하는 원천 요청."""

    venue: Literal["mockex"]


class FeedData(DataModel):
    """원천이 발행하는 체결가. `symbol`은 `"BTC/USD"`처럼 거래소 표기다."""

    price: float
    seq: int


@initialize
def feed(req: FeedRequest) -> FeedRequest:
    """요청 자체를 원천 스테이지의 공유 컨텍스트로 사용한다."""

    return req


@feed
async def _(ctx: FeedRequest, symbols: set[str]):
    """구독 심볼 전체를 한 바퀴 돌며 0.5초 간격으로 체결가를 발행한다.

    `seq`가 0부터 다시 시작하는지 보면 재시작 여부를 데이터만으로도 알 수 있다.
    """

    GEN_STARTS["origin"] += 1
    count = GEN_STARTS["origin"]
    print(f"[ORIGIN]    generator {count}회차 시작 — 상위 구독 심볼 = {sorted(symbols)}")
    seq = 0
    while True:
        for symbol in sorted(symbols):
            yield FeedData(symbol=symbol, price=BASE_PRICE[symbol] + seq, seq=seq)
        seq += 1
        await sleep(0.5)


class QuoteRequest(DependentModel):
    """기초 자산 심볼만 받아 체결가를 돌려주는 파생 요청."""

    market: Literal["spot"]


class QuoteData(DataModel):
    """소비자에게 전달되는 체결가. `symbol`은 `"BTC"`처럼 기초 자산이다."""

    price: float
    seq: int


@QuoteRequest.require
def quote_requirement(req: QuoteRequest, symbols: set[str]):
    """하위 심볼(`BTC`)을 상위 거래소 표기(`BTC/USD`)로 바꾼다.

    **이 콜백이 불렸다는 것 자체가 파생 스테이지가 재시작 경로에 들어섰다는 신호다.**
    합집합이 그대로여서 조기 반환하면 `Domain`은 여기까지 오지 않으므로 `[REQUIRE]`
    줄이 아예 찍히지 않는다.
    """

    upstream = {f"{s}{QUOTE_SUFFIX}" for s in symbols}
    print(f"[REQUIRE]   하위 {sorted(symbols)} -> 상위 {sorted(upstream)}")
    return FeedRequest(venue="mockex"), upstream


@initialize
def quote(req: QuoteRequest) -> QuoteRequest:
    """요청 자체를 파생 스테이지의 공유 컨텍스트로 사용한다."""

    return req


@quote
async def _(ctx: QuoteRequest, symbols: set[str], recv: Receiver):
    """상위 체결가를 받아 심볼을 기초 자산으로 되돌려 발행한다.

    `symbols`는 파생 스테이지 구독자들의 합집합이며, 이 값이 달라질 때만 콜백이 다시
    호출된다. 즉 회차 번호가 곧 합집합이 바뀐 횟수다.
    """

    GEN_STARTS["dependent"] += 1
    count = GEN_STARTS["dependent"]
    print(f"[DEPENDENT] generator {count}회차 시작 — 하위 구독 심볼 = {sorted(symbols)}")
    while True:
        data = await recv()
        feed_data = cast_model(data, FeedData)
        symbol = base_of(feed_data.symbol)
        if symbol not in symbols:
            print(f"warning: 구독하지 않은 심볼이 올라왔다. - {symbol}, {sorted(symbols)}")
            continue
        yield QuoteData(symbol=symbol, price=feed_data.price, seq=feed_data.seq)
