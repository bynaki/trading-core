"""ex06: 합집합이 바뀔 때만 재시작하고, 컨텍스트는 재시작을 넘어 남는다

generator는 심볼 합집합 하나로 돈다(ex05). 그러니 합집합이 바뀌면 `Domain`은 generator를 닫고 새
합집합으로 다시 띄운다. 거꾸로 합집합이 그대로면 아무것도 건드리지 않는다. 이미 누군가 구독 중인
심볼로 소비자가 하나 더 붙으면, 새 소비자는 라우팅에만 등록되어 곧바로 데이터를 받는다.

재시작해도 스테이지는 그대로다. init이 만든 컨텍스트는 남고, generator 안의 지역 변수만 처음부터
다시 시작한다. 재시작 사이에 이어 가야 할 상태(마지막 가격, 시퀀스 번호 등)는 컨텍스트에 둔다.

배우는 것
- 합집합이 그대로면(B가 A와 같은 BTC로 붙음) 재시작하지 않는다.
- 합집합이 넓어지거나(B가 ETH 추가) 좁아지면(B가 떠남) 재시작한다.
- 컨텍스트(`PriceBook`)의 가격은 재시작해도 이어지고, generator의 지역 변수(`run_ticks`)는 0부터다.

실행
    uv run examples/ex06_restart.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex06: ----- 1. A가 {'BTC'} 구독 -----
    ex06.tick: generator 1회차 시작 {symbols=['BTC']}
    ex06: ----- 2. B도 {'BTC'} 구독: 합집합 그대로 -----
    ex06: B가 재시작 없이 받는다 {b=2}
    ex06: ----- 3. B가 {'BTC', 'ETH'}로: 합집합이 넓어진다 -----
    ex06.tick: generator 1회차 끝 {run_ticks=5}
    ex06.tick: generator 2회차 시작 {symbols=['BTC', 'ETH']}
    ex06: ----- 4. B가 떠난다: 합집합이 좁아진다 -----
    ex06.tick: generator 2회차 끝 {run_ticks=6}
    ex06.tick: generator 3회차 시작 {symbols=['BTC']}
    ex06.tick: generator 3회차 끝 {run_ticks=3}
    ex06: A가 받은 BTC 가격은 재시작을 넘어 이어진다 {first=101.0, last=111.0, count=11}
    (건수는 실행마다 조금씩 다르다)

다음: ex07_derived.py — 다른 요청의 데이터를 받아 가공하는 파생 요청
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, SourceRequest, cast_model, initialize
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
BASE_PRICE = {"BTC": 100.0, "ETH": 200.0}

log = get_logger("ex06")
tick_log = get_logger("ex06.tick")

STARTS: list[list[str]] = []
"""generator가 (재)시작할 때마다 받은 심볼."""


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    exchange: str


class TickData(DataModel):
    price: float


class PriceBook:
    """스테이지 컨텍스트. 심볼별 마지막 가격을 들고 있어 재시작해도 가격이 이어진다."""

    def __init__(self) -> None:
        self.last = dict(BASE_PRICE)

    def next_price(self, symbol: str) -> float:
        self.last[symbol] += 1
        return self.last[symbol]


@initialize
def tick(req: TickReq) -> PriceBook:
    return PriceBook()


@tick
async def _(book: PriceBook, symbols: set[str]):
    STARTS.append(sorted(symbols))
    run = len(STARTS)
    tick_log.info(f"generator {run}회차 시작", symbols=sorted(symbols))
    run_ticks = 0  # 지역 변수: 재시작하면 0부터
    try:
        while True:
            for symbol in sorted(symbols):
                run_ticks += 1
                yield TickData(symbol=symbol, price=book.next_price(symbol))
            await asyncio.sleep(INTERVAL)
    finally:
        tick_log.info(f"generator {run}회차 끝", run_ticks=run_ticks)


# ===== 소비자 쪽 =====


class Recorder:
    def __init__(self) -> None:
        self.prices: dict[str, list[float]] = {}

    async def __call__(self, data: DataModel) -> None:
        tick = cast_model(data, TickData)
        self.prices.setdefault(tick.symbol, []).append(tick.price)

    @property
    def count(self) -> int:
        return sum(len(prices) for prices in self.prices.values())


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 합집합이 바뀔 때만 재시작한다 ━━━━━━━━━━")
    STARTS.clear()
    req = TickReq(exchange="mock")
    a, b = Recorder(), Recorder()

    async with domain.subscribe(req, a) as sub_a:
        log.info("----- 1. A가 {'BTC'} 구독 -----")
        await sub_a.update({"BTC"})
        await asyncio.sleep(0.5)

        async with domain.subscribe(req, b) as sub_b:
            log.info("----- 2. B도 {'BTC'} 구독: 합집합 그대로 -----")
            await sub_b.update({"BTC"})
            await asyncio.sleep(0.5)
            log.info("B가 재시작 없이 받는다", b=b.count)
            assert len(STARTS) == 1 and b.count > 0

            log.info("----- 3. B가 {'BTC', 'ETH'}로: 합집합이 넓어진다 -----")
            await sub_b.update({"BTC", "ETH"})
            await asyncio.sleep(0.5)
            assert len(STARTS) == 2

            log.info("----- 4. B가 떠난다: 합집합이 좁아진다 -----")
        await asyncio.sleep(0.5)
        assert len(STARTS) == 3

    btc = a.prices["BTC"]
    log.info(
        "A가 받은 BTC 가격은 재시작을 넘어 이어진다", first=btc[0], last=btc[-1], count=len(btc)
    )
    assert STARTS == [["BTC"], ["BTC", "ETH"], ["BTC"]]
    # 가격이 처음(101)으로 돌아가지 않고 하나씩 이어 오른다.
    assert btc == [BASE_PRICE["BTC"] + i for i in range(1, len(btc) + 1)]
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
