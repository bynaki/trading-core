"""ex01: 가장 작은 소스 요청과 `Domain.stream()`

trading-core를 쓰는 일은 두 쪽으로 나뉜다.

- **binder 쪽**: 요청 모델을 정의하고, 그 요청이 오면 데이터를 어떻게 만들지 콜백으로 등록한다.
  실제라면 여기서 거래소에 접속하고 메시지를 파싱한다.
- **소비자 쪽**: `Domain`에 요청과 심볼을 주고 데이터를 받는다. 접속·공유·정리는 `Domain`이 한다.

이 예제는 두 쪽을 가장 작게 보인다.

배우는 것
- `SourceRequest`(요청)와 `DataModel`(데이터)을 pydantic 모델처럼 정의한다.
- `@initialize`가 init 콜백의 첫 인자 어노테이션(`req: TickReq`)으로 요청 타입을 알아내 binder를
  등록한다. 그 binder를 데코레이터로 쓰면(`@tick`) generate 콜백이 등록된다.
- generate 콜백은 구독 심볼 집합을 받아 데이터를 끝없이 `yield`하는 async generator다.
- 소비자는 `Domain.start()` → `domain.stream(요청, 심볼)` → `Domain.stop()` 순서로 쓴다.
- `stream()`이 주는 데이터의 타입은 `DataModel`이다. `cast_model()`로 실제 타입으로 좁힌다(종류가
  여럿이면 ex30처럼 `match`로 가른다).

실행
    uv run examples/ex01_stream.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex01: ━━━━━━━━━━ 시작: 가장 작은 소스 요청과 Domain.stream() ━━━━━━━━━━
    ex01.tick: generator 시작 {symbols=['BTC', 'ETH']}
    ex01: 수신 {symbol=BTC, price=100.0}
    ex01: 수신 {symbol=ETH, price=200.0}
    ex01: 수신 {symbol=BTC, price=101.0}
    ...
    ex01: ━━━━━━━━━━ 끝 ━━━━━━━━━━

다음: ex02_subscribe.py — 구독을 열어 둔 채 심볼을 바꾸는 저수준 API
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, SourceRequest, cast_model, initialize
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
"""예제 공용 로그 설정."""

INTERVAL = 0.2
"""가짜 거래소가 체결가를 내보내는 간격(초)."""

BASE_PRICE = {"BTC": 100.0, "ETH": 200.0, "XRP": 300.0}
"""심볼별 시작 가격. 가짜 거래소는 바퀴마다 1씩 올린다."""

log = get_logger("ex01")
"""소비자 쪽 로거. 로거 이름이 줄 앞에 붙어 어느 예제의 줄인지 알려 준다."""
tick_log = get_logger("ex01.tick")
"""binder 쪽 로거."""


# ===== binder 쪽: 요청·데이터 모델과 콜백 =====


class TickReq(SourceRequest):
    """가짜 거래소에 체결가를 요청한다. 필드(`exchange`)가 요청의 '내용'이다."""

    exchange: str


class TickData(DataModel):
    """체결가 한 건. `symbol` 필드는 `DataModel`에 이미 있다(어느 소비자에게 보낼지 정하는 키)."""

    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    """init 콜백. 스테이지가 설 때 한 번 불려 '컨텍스트'를 만든다.

    컨텍스트는 generate 콜백의 첫 인자로 넘어간다. 실제라면 거래소 연결을 담을 자리다. 여기서는
    요청을 그대로 컨텍스트로 쓴다.
    """

    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """generate 콜백. 구독할 심볼 집합을 받아 데이터를 끝없이 내보낸다.

    스스로 끝나지 않는다. 소비자가 그만 받으면 `Domain`이 이 generator를 닫는다.
    """

    tick_log.info("generator 시작", symbols=sorted(symbols))
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    """BTC·ETH 체결가를 6건 받고 그만둔다."""

    log.info("━━━━━━━━━━ 시작: 가장 작은 소스 요청과 Domain.stream() ━━━━━━━━━━")
    received: list[TickData] = []
    # `async with`를 벗어나면 구독이 끊기고 generator가 닫힌다. `break`로 일찍 나와도 마찬가지다.
    async with domain.stream(TickReq(exchange="mock"), {"BTC", "ETH"}) as stream:
        async for data in stream:
            tick = cast_model(data, TickData)  # `DataModel` → `TickData`
            log.info("수신", symbol=tick.symbol, price=tick.price)
            received.append(tick)
            if len(received) == 6:
                break

    # 요청한 심볼만 왔다.
    assert {tick.symbol for tick in received} == {"BTC", "ETH"}
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")  # 끝의 "\n"은 다음 예제와의 빈 줄


async def main() -> None:
    """이 파일을 직접 실행할 때: 로그를 구성하고 `Domain`을 시작해 예제를 돌린 뒤 멈춘다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()  # `Domain`은 시작해야 generator를 돌린다
    try:
        await run_ex(domain)
    finally:
        await domain.stop()  # 남은 태스크를 모두 취소한다


if __name__ == "__main__":
    asyncio.run(main())
