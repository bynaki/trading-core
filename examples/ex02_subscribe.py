"""ex02: `Domain.subscribe()`로 구독 심볼 바꾸기

`stream()`은 심볼을 처음에 한 번 정하고 끝까지 간다. 실제 앱은 구독을 열어 둔 채 심볼을 넣었다
뺐다 한다. 그럴 때 쓰는 저수준 API가 `Domain.subscribe()`다.

배우는 것
- `domain.subscribe(요청, sender)`는 `Subscription`을 준다. 데이터는 `sender`로 들어온다.
- `Sender`는 데이터 하나를 받는 async 함수면 무엇이든 된다(`async def f(data) -> None`).
  `__call__`을 가진 객체도 된다.
- `sub.update(심볼)`은 **교체**다. 추가가 아니다. `{"BTC"}` 다음에 `{"ETH"}`를 주면 BTC는 빠진다.
- 빈 집합 `update(set())`은 구독 해제다. 구독 객체는 남아 있어 다시 `update()`할 수 있다.
- `async with` 블록을 벗어나면 구독이 끊긴다(`detach`).
- `domain.get_shared_symbols(content_id)`로 소스 generator가 지금 돌리는 심볼을 볼 수 있다.

실행
    uv run examples/ex02_subscribe.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex02: ----- update({'BTC'}) -----
    ex02.tick: generator 시작 {symbols=['BTC']}
    ex02: 수신 {symbol=BTC, price=100.0}
    ...
    ex02: ----- update({'ETH', 'XRP'}): 교체라 BTC는 빠진다 -----
    ex02.tick: generator 시작 {symbols=['ETH', 'XRP']}
    ex02: 수신 {symbol=ETH, price=200.0}
    ex02: 수신 {symbol=XRP, price=300.0}
    ...
    ex02: ----- update(set()): 구독 해제 -----
    ex02: 소스 generator가 돌리는 심볼 {shared=[]}

다음: ex03_cleanup.py — 구독이 바뀔 때와 끝날 때 binder가 정리하는 자리
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, SourceRequest, cast_model, initialize
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
BASE_PRICE = {"BTC": 100.0, "ETH": 200.0, "XRP": 300.0}

log = get_logger("ex02")
tick_log = get_logger("ex02.tick")


# ===== binder 쪽 (ex01과 같다) =====


class TickReq(SourceRequest):
    exchange: str


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    tick_log.info("generator 시작", symbols=sorted(symbols))
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    """심볼을 교체하고, 비우고, 다시 넣으며 무엇이 들어오는지 본다."""

    log.info("━━━━━━━━━━ 시작: Domain.subscribe()로 구독 심볼 바꾸기 ━━━━━━━━━━")
    req = TickReq(exchange="mock")
    received: list[str] = []  # 받은 심볼을 차례로 모은다

    async def on_tick(data: DataModel) -> None:
        """Sender. 소스 generator가 데이터를 낼 때마다 불린다."""

        tick = cast_model(data, TickData)
        log.info("수신", symbol=tick.symbol, price=tick.price)
        received.append(tick.symbol)

    def shared() -> list[str]:
        """소스 generator가 지금 돌리는 심볼."""

        return sorted(domain.get_shared_symbols(req.tr_content_id))

    async with domain.subscribe(req, on_tick) as sub:
        # 구독을 막 만든 상태에서는 아무것도 오지 않는다. 심볼을 넣어야 소스 generator가 돈다.
        log.info("----- update({'BTC'}) -----")
        await sub.update({"BTC"})
        await asyncio.sleep(0.5)
        assert set(received) == {"BTC"}

        log.info("----- update({'ETH', 'XRP'}): 교체라 BTC는 빠진다 -----")
        await sub.update({"ETH", "XRP"})
        received.clear()  # `update()`는 이전 generator를 닫고 돌아온다. 이 뒤로 BTC는 오지 않는다
        await asyncio.sleep(0.5)
        assert set(received) == {"ETH", "XRP"}

        log.info("----- update(set()): 구독 해제 -----")
        await sub.update(set())
        log.info("소스 generator가 돌리는 심볼", shared=shared())
        received.clear()
        await asyncio.sleep(0.5)
        assert received == [] and shared() == []

        log.info("----- 같은 구독으로 다시 update({'BTC'}) -----")
        await sub.update({"BTC"})
        log.info("소스 generator가 돌리는 심볼", shared=shared())
        await asyncio.sleep(0.5)
        assert set(received) == {"BTC"}

    # 블록을 벗어나며 구독이 끊겼다.
    log.info("블록을 벗어난 뒤 소스 generator가 돌리는 심볼", shared=shared())
    assert shared() == []
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
