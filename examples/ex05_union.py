"""ex05: binder는 합집합을 받고, 데이터는 구독한 소비자에게만 간다

같은 요청을 여러 소비자가 서로 다른 심볼로 구독하면 스테이지는 하나다(ex04). 그 하나의 generator가
모두의 심볼을 돌려야 하므로 `Domain`은 binder에 **구독 심볼의 합집합**을 넘긴다. 나올 때는 반대로
데이터의 `symbol`을 보고 그 심볼을 구독한 소비자에게만 나눠 준다(fan-out).

    A {BTC, ETH} ─┐                                  ┌─→ A: BTC, ETH
                  ├─→ generator {BTC, ETH, XRP} ─→ ─┤
    B {ETH, XRP} ─┘                                  └─→ B: ETH, XRP   (ETH는 둘 다)

배우는 것
- binder는 소비자가 몇인지 모른다. 심볼 합집합 하나만 본다.
- 데이터의 `symbol` 필드가 라우팅 키다. 소비자는 자기가 구독한 심볼만 받는다.
- `domain.get_shared_symbols()`가 돌려주는 것이 바로 이 합집합이다.

실행
    uv run examples/ex05_union.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex05: 소스 generator가 돌리는 합집합 {shared=['BTC', 'ETH', 'XRP']}
    ex05.tick: generator 시작 {symbols=['BTC', 'ETH', 'XRP']}
    ex05: 받은 심볼 {a=['BTC', 'ETH'], b=['ETH', 'XRP']}

다음: ex06_restart.py — 합집합이 바뀌면 generator는 어떻게 되나
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, SourceRequest, initialize
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
BASE_PRICE = {"BTC": 100.0, "ETH": 200.0, "XRP": 300.0}

log = get_logger("ex05")
tick_log = get_logger("ex05.tick")


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    exchange: str


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """`symbols`는 모든 소비자가 구독한 심볼의 합집합이다."""

    tick_log.info("generator 시작", symbols=sorted(symbols))
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== 소비자 쪽 =====


class Recorder:
    """받은 심볼을 모으는 Sender."""

    def __init__(self) -> None:
        self.symbols: set[str] = set()

    async def __call__(self, data: DataModel) -> None:
        self.symbols.add(data.symbol)


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: binder는 합집합을 받고, 데이터는 구독한 소비자에게만 ━━━━━━━━━━")
    req = TickReq(exchange="mock")
    a, b = Recorder(), Recorder()

    async with domain.subscribe(req, a) as sub_a, domain.subscribe(req, b) as sub_b:
        await sub_a.update({"BTC", "ETH"})
        await sub_b.update({"ETH", "XRP"})
        shared = domain.get_shared_symbols(req.tr_content_id)
        log.info("소스 generator가 돌리는 합집합", shared=sorted(shared))
        await asyncio.sleep(0.6)

    log.info("받은 심볼", a=sorted(a.symbols), b=sorted(b.symbols))
    assert shared == {"BTC", "ETH", "XRP"}
    assert a.symbols == {"BTC", "ETH"}
    assert b.symbols == {"ETH", "XRP"}
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
