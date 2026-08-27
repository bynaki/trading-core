"""같은 내용의 `RequestModel` 두 개가 컨텍스트를 공유하지 않는 것을 보이는 예제.

`GenerateModel`과 `DependentModel`은 **content_id 단위로 공유**된다. 필드 값이 같은
요청을 두 소비자가 보내면 `Domain`은 `_origin_stage_dict[content_id]`에 있는 하나의
원천 스테이지를 재사용하고, init 콜백은 한 번만 불린다.

`RequestModel`(instanter)은 그렇지 않다. `Domain._define_inst_stage()`는
`_origin_stage_dict`를 아예 보지 않는다. 요청을 보낼 때마다 새 스테이지를 만들고 init
콜백을 다시 불러 **자기만의 컨텍스트**를 갖는다. content_id가 같아도 마찬가지다.

이 예제는 그 차이를 한 화면에 겹쳐 놓는다.

- 원천 `BeatReq`는 두 소비자가 하나를 공유한다 — `BeatCtx`가 한 번만 만들어진다.
- 요청형 `WatchReq(quote="USD")`는 두 소비자가 각각 갖는다 — content_id가 같은데도
  `WatchCtx`가 두 번 만들어지고, 같은 `"BTC"` 슬롯이 스테이지마다 따로 열린다.

컨텍스트가 나뉜다는 것은 `WatchCtx.seen` 같은 상태가 소비자별로 따로 센다는 뜻이다.
공유된다면 두 소비자의 수신 건수가 하나의 카운터에 섞여 올라갔을 것이다.
"""

from asyncio import sleep
from typing import Literal

from pydantic import BaseModel

from trading_core import DataModel, GenerateModel, Runnable, initialize
from trading_core.model import RequestModel

INIT_PRICE_DICT: dict[str, float] = {
    "BTC/USD": 100,
    "ETH/USD": 200,
}
"""원천이 발행을 시작할 가격. 키는 상위 표기다."""

type QuoteType = Literal["USD"]


class BeatReq(GenerateModel):
    """상위 원천 요청. 필드가 없으므로 content_id가 하나뿐이다."""


class BeatData(DataModel):
    """상위 표기(`"BTC/USD"`)로 발행되는 현재가."""

    price: float


class BeatCtx(BaseModel):
    """원천 스테이지의 컨텍스트. 몇 번째로 만들어졌는지 기억한다."""

    no: int
    current_price_dict: dict[str, float]


_beat_ctx_count = 0
"""`BeatCtx`가 만들어진 횟수. 공유되면 1에서 더 늘지 않는다."""


@initialize
def beat(req: BeatReq) -> BeatCtx:
    """원천 컨텍스트를 만든다. 이 예제에서는 **한 번만** 불려야 한다."""

    global _beat_ctx_count
    _beat_ctx_count += 1
    print(f"[ex08] BeatCtx 생성 #{_beat_ctx_count}")
    return BeatCtx(no=_beat_ctx_count, current_price_dict=INIT_PRICE_DICT.copy())


@beat
async def _(ctx: BeatCtx, symbols: set[str]):
    """구독된 상위 표기를 돌며 가격을 1씩 올려 발행한다."""

    while True:
        for symbol in sorted(symbols):
            yield BeatData(symbol=symbol, price=ctx.current_price_dict[symbol])
            ctx.current_price_dict[symbol] += 1
            await sleep(0.5)


class WatchReq(RequestModel):
    """관찰 요청. 필드가 `quote` 하나뿐이라 같은 값이면 content_id가 같다.

    그런데도 이 요청으로 만든 스테이지는 서로 공유되지 않는다. 그것이 이 예제의 주제다.
    """

    quote: QuoteType


class WatchData(DataModel):
    """하위 표기(`"BTC"`)로 나가는 출력. 어느 컨텍스트를 거쳤는지 함께 싣는다."""

    ctx_no: int
    seen: int
    price: float


class WatchCtx(BaseModel):
    """요청형 스테이지의 컨텍스트.

    `seen`은 이 스테이지가 지금까지 내보낸 데이터 수다. 컨텍스트가 공유된다면 두
    소비자의 수신이 이 하나의 카운터에 섞이겠지만, 실제로는 스테이지마다 따로 센다.
    """

    no: int
    quote: QuoteType
    seen: int = 0


_watch_ctx_count = 0
"""`WatchCtx`가 만들어진 횟수. 요청을 보낸 수만큼 늘어난다."""


@initialize
def watch(req: WatchReq) -> WatchCtx:
    """요청형 컨텍스트를 만든다. content_id가 같아도 요청마다 다시 불린다."""

    global _watch_ctx_count
    _watch_ctx_count += 1
    print(f"[ex08] WatchCtx 생성 #{_watch_ctx_count} - content_id={req.get_tr_content_id()}")
    return WatchCtx(no=_watch_ctx_count, quote=req.quote)


class WatchRunnable(Runnable):
    """상위 `BeatData`를 하위 표기의 `WatchData`로 바꾸는 시퀀스 단계.

    자기 스테이지의 컨텍스트를 들고 있다가 `seen`을 올린다. 이 값이 스테이지별로 따로
    세어지는 것이 컨텍스트가 나뉘어 있다는 증거다.
    """

    def __init__(self, ctx: WatchCtx, symbol: str):
        self.ctx = ctx
        self.symbol = symbol

    async def invoke(self, input: BeatData) -> WatchData:
        """`seen`을 하나 올리고 하위 표기로 되돌려 내보낸다."""

        self.ctx.seen += 1
        return WatchData(
            symbol=self.symbol,
            ctx_no=self.ctx.no,
            seen=self.ctx.seen,
            price=input.price,
        )


@watch
async def _(ctx: WatchCtx, symbol: str):
    """하위 심볼 하나를 상위 표기로 바꿔 구독하는 시퀀스를 낸다.

    두 소비자가 같은 `"BTC"`를 구독해도 이 콜백은 스테이지마다 한 번씩, 즉 **두 번**
    불린다. 스테이지가 공유된다면 한 번이었을 것이다.
    """

    print(f"[ex08] bind   ctx#{ctx.no} symbol={symbol}")
    yield BeatReq()(f"{symbol}/{ctx.quote}") | WatchRunnable(ctx, symbol)


@watch.unbind
async def _(ctx: WatchCtx, symbol: str):
    """슬롯이 닫힐 때 불린다. 슬롯이 스테이지마다 따로 있으므로 이것도 두 번 불린다."""

    print(f"[ex08] unbind ctx#{ctx.no} symbol={symbol}")


@watch.detached
async def _(ctx: WatchCtx):
    """스테이지 전체가 닫힐 때 불린다. 마지막 `seen` 값을 남긴다."""

    print(f"[ex08] detach ctx#{ctx.no} seen={ctx.seen}")
