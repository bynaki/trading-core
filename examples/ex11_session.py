"""ex11: 심볼마다 따로 도는 세션 요청 — bind, `Pipeline`, `Runnable`

지금까지의 요청(소스·파생)은 "심볼 집합 하나 → generator 하나"였다. 심볼마다 상태를 들고 계산해야
하는 일(직전 가격과의 차이, 차트 지표 등)은 그 구조에서 심볼별 상태를 직접 나눠 관리해야 한다.

**세션 요청**(`SessionRequest`)은 심볼마다 **슬롯** 하나를 만든다. 슬롯은 bind 콜백이 돌려준
**파이프라인**으로 상위 소스 스테이지에 붙는다.

    소비자 {"BTC","ETH"}
      ├─ 슬롯 BTC: TickReq()("BTC/USD") | Change("BTC") ─┐
      └─ 슬롯 ETH: TickReq()("ETH/USD") | Change("ETH") ─┴→ 소스 스테이지 {"BTC/USD","ETH/USD"}

- **bind 콜백**(`@change`)은 심볼 하나를 받아 파이프라인을 yield한다. 새 심볼이 구독될 때마다
  그 심볼로 한 번 불린다.
- **파이프라인**은 `상위요청(상위 심볼) | 단계 | ...`로 만든다. `TickReq()("BTC/USD")`가 "이 상위
  요청의 이 심볼에서 시작한다"는 뜻이다.
- **단계**는 `Runnable`이다. `async def invoke(self, input)`가 데이터 하나를 받아 하나를 돌려준다.
  `None`을 돌려주면 그 데이터는 거기서 버려진다.

**상위 표기와 하위 표기**: bind가 받는 `symbol`은 소비자가 쓴 하위 표기(`"BTC"`)다. 파이프라인
머리에 넣는 것은 소스 스테이지가 아는 상위 표기(`"BTC/USD"`)다. 둘을 바꿔 쓰는 실수가 흔하니
변수 이름을 나눠 두자.

배우는 것
- 세션 요청은 `@initialize`(init) + `@x`(bind)로 등록한다. bind는 `(ctx, symbol)`을 받는다.
- 단계 객체는 슬롯마다 따로 만들어지므로 심볼별 상태(`last`)를 안전하게 들 수 있다.
- 첫 틱은 비교할 직전 가격이 없어 `None`으로 거른다. 그래서 소비자가 받는 첫 가격은 101이다.
- 세션의 출력은 심볼로 라우팅되지 않고 그 구독의 소비자에게 바로 간다. 출력의 `symbol`을 하위
  표기로 맞춰 주는 것은 소비자를 위한 일이다.

실행
    uv run examples/ex11_session.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex11.change: init
    ex11.change: bind {symbol=BTC, upstream=BTC/USD}
    ex11.change: bind {symbol=ETH, upstream=ETH/USD}
    ex11: 소스 스테이지가 돌리는 심볼 {shared=['BTC/USD', 'ETH/USD']}
    ex11: 수신 {symbol=BTC, price=101.0, change=1.0}
    ex11: 수신 {symbol=ETH, price=201.0, change=1.0}
    ...
    (BTC·ETH의 bind 순서는 실행마다 바뀔 수 있다)

다음: ex12_unbind.py — 심볼이 빠질 때와 구독이 끝날 때의 정리
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
INTERVAL = 0.2
BASE_PRICE = {"BTC/USD": 100.0, "ETH/USD": 200.0}

log = get_logger("ex11")
change_log = get_logger("ex11.change")


# ===== binder 쪽 (1): 소스 요청 — 거래소 표기 =====


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
            yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 세션 요청 — 직전 가격과의 차이 =====


class ChangeReq(SessionRequest):
    pass


class ChangeData(DataModel):
    price: float
    change: float
    """직전 틱보다 오른 만큼."""


class Change(Runnable[TickData, ChangeData]):
    """파이프라인 단계. 슬롯(심볼)마다 하나씩 만들어진다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol  # 하위 표기
        self.last: float | None = None  # 이 심볼의 직전 가격

    async def invoke(self, input: TickData) -> ChangeData | None:
        last, self.last = self.last, input.price
        if last is None:
            return None  # 첫 틱은 비교할 것이 없다 — 거른다
        return ChangeData(symbol=self.symbol, price=input.price, change=input.price - last)


@initialize
def change(req: ChangeReq) -> ChangeReq:
    change_log.info("init")
    return req


@change
async def _(ctx: ChangeReq, symbol: str):
    """bind 콜백. `symbol`은 하위 표기다. 상위 표기로 바꿔 파이프라인 머리를 만든다."""

    upstream_symbol = f"{symbol}/USD"
    change_log.info("bind", symbol=symbol, upstream=upstream_symbol)
    yield TickReq()(upstream_symbol) | Change(symbol)


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 심볼마다 따로 도는 세션 요청 ━━━━━━━━━━")
    received: list[ChangeData] = []

    # 세션 요청도 소스 요청처럼 stream()·subscribe()로 쓴다.
    # stream()은 첫 데이터를 기다릴 때 구독을 시작한다.
    shared: set[str] = set()
    async with domain.stream(ChangeReq(), {"BTC", "ETH"}) as stream:
        async for data in stream:
            if not received:
                shared = domain.get_shared_symbols(TickReq().tr_content_id)
                log.info("소스 스테이지가 돌리는 심볼", shared=sorted(shared))
            item = cast_model(data, ChangeData)
            log.info("수신", symbol=item.symbol, price=item.price, change=item.change)
            received.append(item)
            if len(received) == 4:
                break

    assert shared == {"BTC/USD", "ETH/USD"}  # 상위에는 상위 표기로 붙는다
    assert {item.symbol for item in received} == {"BTC", "ETH"}  # 소비자는 하위 표기로 받는다
    assert all(item.change == 1.0 for item in received)
    # 첫 틱(100·200)은 None으로 걸렀다.
    first_btc = next(item for item in received if item.symbol == "BTC")
    assert first_btc.price == BASE_PRICE["BTC/USD"] + 1
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
