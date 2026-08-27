"""`RequestModel`(instanter) 경로로 원천 틱에서 변동폭을 계산하는 예제.

ex01~ex06의 요청은 "심볼 집합 하나 → generator 하나"였다. `RequestModel`은 다르다.
**심볼마다 슬롯 하나**를 만들고, 각 슬롯이 `Sequence`로 상위 원천에 붙는다. 이 예제의
`SwingReq`는 하위 심볼 `"BTC"` 하나마다 상위 원천 `TickReq`의 `"BTC/USD"`를 구독하는
시퀀스를 만들고, 그 사이에 `SwingRunnable`을 끼워 직전 가격과의 차이를 계산한다.

핵심은 **상위 표기와 하위 표기가 다르다**는 것이다.

- 상위 표기 — 원천 generator가 아는 심볼(`"BTC/USD"`). `req(symbol)`에 넘기는 값이다.
- 하위 표기 — 소비자가 구독한 심볼(`"BTC"`). bind 콜백이 인자로 받는 값이다.

`SwingReq(quote="USD")`를 `{"BTC"}`로 구독하면 상위에는 `"BTC/USD"`가 올라가고 소비자는
`"BTC"`로 받는다. 이 변환을 시퀀스가 담당한다.
"""

import re
from asyncio import sleep
from typing import Literal

from pydantic import BaseModel

from trading_core import DataModel, GenerateModel, initialize
from trading_core.model import RequestModel, Runnable

INIT_PRICE_DICT: dict[str, float] = {
    "BTC/USD": 100,
    "ETH/USD": 200,
    "XRP/USD": 300,
    "BTC/KRW": 1000,
    "ETH/KRW": 2000,
    "XRP/KRW": 3000,
}
"""원천이 발행을 시작할 가격. 견적 통화별로 따로 둔다."""

type QuoteType = Literal["USD", "KRW"]

_SYMBOL_PATTERN = re.compile(r"^([A-Z0-9]+)/([A-Z0-9]+)$")


def base_of(symbol: str) -> str:
    """`"BTC/USD"`처럼 `기초/견적` 형식인 심볼에서 기초 자산(`"BTC"`)만 뽑아낸다."""
    matched = _SYMBOL_PATTERN.match(symbol)
    if matched is None:
        raise ValueError(f"'{symbol}'은(는) '기초/견적' 형식의 심볼이 아니다")
    return matched.group(1)


def quote_of(symbol: str) -> str:
    """`"BTC/USD"`처럼 `기초/견적` 형식인 심볼에서 견적 자산(`"USD"`)만 뽑아낸다."""
    matched = _SYMBOL_PATTERN.match(symbol)
    if matched is None:
        raise ValueError(f"'{symbol}'은(는) '기초/견적' 형식의 심볼이 아니다")
    return matched.group(2)


class TickReq(GenerateModel):
    """상위 원천 요청. 필드가 없으므로 모든 소비자가 하나의 원천을 공유한다."""


class TickData(DataModel):
    """상위 표기(`"BTC/USD"`)로 발행되는 현재가."""

    price: float


class TickCtx(BaseModel):
    """원천 스테이지가 공유하는 컨텍스트. 심볼별 현재가를 들고 있다."""

    current_price_dict: dict[str, float]


@initialize
def tick(req: TickReq) -> TickCtx:
    """원천의 공유 컨텍스트를 만든다. 시작 가격표를 복사해 둔다."""

    return TickCtx(current_price_dict=INIT_PRICE_DICT.copy())


@tick
async def _(ctx: TickCtx, symbols: set[str]):
    """구독 심볼을 돌며 가격을 1씩 올려 발행한다.

    여기서 받는 `symbols`는 **상위 표기**의 합집합이다(`{"BTC/USD", ...}`).
    시퀀스가 요구한 심볼이 그대로 올라오므로 `current_price_dict`의 키와 맞는다.
    """

    while True:
        for symbol in symbols:
            yield TickData(symbol=symbol, price=ctx.current_price_dict[symbol])
            ctx.current_price_dict[symbol] += 1
            await sleep(0.5)


class SwingReq(RequestModel):
    """견적 통화를 골라 변동폭을 요청한다.

    `quote`는 `content_id`에 들어가므로 `quote="USD"`와 `quote="KRW"`는 서로 다른
    스테이지가 된다.
    """

    quote: QuoteType


class SwingData(DataModel):
    """하위 표기(`"BTC"`)로 나가는 변동폭 출력."""

    quote: QuoteType
    price: float
    swing: float


class SwingCtx(BaseModel):
    """요청형 스테이지가 공유하는 컨텍스트."""

    quote: QuoteType
    symbols: set[str] = set()


@initialize
def swing(req: SwingReq):
    """요청형 스테이지의 공유 컨텍스트를 만든다. 견적 통화를 기억해 둔다."""

    return SwingCtx(quote=req.quote)


class SwingRunnable(Runnable):
    """직전 가격과의 차이를 계산하는 시퀀스 단계.

    **심볼마다 별개의 인스턴스**가 만들어지므로 `active_price`를 안전하게 들고 있을 수
    있다. 슬롯이 심볼 단위라는 점이 여기서 드러난다.

    상위 표기로 들어온 `TickData`를 하위 표기의 `SwingData`로 바꾸는 것도 이 단계의
    몫이다. `self.symbol`이 하위 표기다.
    """

    def __init__(self, quote: QuoteType, symbol: str):
        self.quote: QuoteType = quote
        self.symbol = symbol
        self.active_price = 0

    async def invoke(self, input: TickData) -> SwingData | None:
        """변동폭을 계산해 내보낸다. 첫 틱은 기준가만 잡고 `None`을 돌려준다.

        `None`을 돌려주면 그 데이터는 소비자에게 가지 않는다. 비교할 직전 가격이 없는
        첫 틱을 걸러내는 데 쓴다.
        """

        if self.active_price == 0:
            self.active_price = input.price
            return
        swing_val = input.price - self.active_price
        self.active_price = input.price
        return SwingData(symbol=self.symbol, quote=self.quote, price=input.price, swing=swing_val)


@swing
async def _(ctx: SwingCtx, symbol: str):
    """하위 심볼 하나를 상위 표기로 바꿔 구독하는 시퀀스를 낸다.

    `symbol`은 소비자가 구독한 하위 표기(`"BTC"`)이고, `TickReq()(...)`에 넘기는
    `f"{symbol}/{ctx.quote}"`가 상위 표기(`"BTC/USD"`)다. `|`로 이어 붙인 `Runnable`이
    상위 데이터를 하위 출력으로 되돌린다.

    이 콜백은 심볼이 새로 구독될 때마다 한 번씩 불린다.
    """

    seq = TickReq()(f"{symbol}/{ctx.quote}") | SwingRunnable(ctx.quote, symbol)
    yield seq
