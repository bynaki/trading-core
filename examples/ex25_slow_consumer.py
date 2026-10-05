"""ex25: 느린 소비자가 공유 generator를 붙잡을 때 — 자기 큐로 떼어 내기

소스 generator는 데이터를 하나 yield할 때마다 그 심볼을 구독한 Sender를 **모두 부르고 끝나기를
기다린** 뒤에 다음 데이터로 간다. 그래서 Sender 하나가 느리면 generator 전체가 그 속도로 늦어지고,
같은 스테이지를 나눠 쓰는 빠른 소비자도 덩달아 덜 받는다.

    generator ─ yield ─→ 빠른 Sender  (곧 끝남)
                     └─→ 느린 Sender  (0.3초)   ← generator가 이것을 기다린다

코어는 이것을 막아 주지 않는다. 데이터를 버릴지, 쌓아 둘지는 소비자마다 다르기 때문이다. 느린
소비자는 Sender에서 **자기 큐에 넣기만 하고** 바로 돌아오고, 실제 처리는 따로 띄운 태스크에서 한다.
큐가 차면 어떻게 할지(가장 오래된 것을 버린다, 막는다 등)도 소비자가 정한다. 이 예제는 최신 가격만
의미 있다고 보고 가장 오래된 것을 버린다.

배우는 것
- Sender가 느리면 같은 소스 스테이지의 다른 소비자까지 느려진다.
- Sender는 빨리 돌아와야 한다. 무거운 일은 자기 큐와 태스크로 넘긴다.
- 큐가 찰 때의 정책은 소비자가 정한다.

실행
    uv run examples/ex25_slow_consumer.py

기대 출력 (줄 앞의 레벨은 뺐다)
    ex25: ----- 1. 느린 Sender와 빠른 소비자가 스테이지를 나눠 쓴다 -----
    ex25: 받은 건수 {fast=3, slow=2}
    ex25: ----- 2. 느린 소비자가 자기 큐로 받는다 -----
    ex25: 받은 건수 {fast=20, slow=3, dropped=13}
    (건수는 실행마다 조금씩 다르다)

1단계의 빠른 소비자는 1초에 20건쯤 받을 수 있는데 3건만 받았다. 느린 Sender가 한 건에 0.3초씩
generator를 붙잡았기 때문이다. 2단계에서는 제 속도로 받았다. 느린 소비자가 처리한 건수는 어느
쪽이든 비슷하다. 다만 2단계는 그사이 쌓인 오래된 가격을 버리고 최신 것을 처리한다.

`stream()`도 내부에서 큐를 쓰지만 크기 제한이 없다. 받는 쪽이 계속 느리면 데이터가 끝없이 쌓인다.

다음: ex26_mistakes.py — 등록·사용 실수
"""

import asyncio
import contextlib
from pathlib import Path

from trading_core import DataModel, Domain, SourceRequest, initialize
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.05
WORK = 0.3
"""느린 소비자가 데이터 하나를 처리하는 시간."""
WINDOW = 1.0
"""단계마다 받는 시간."""

log = get_logger("ex25")


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    seq: int


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, seq=n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== 소비자 쪽 =====


class Counter:
    """빠른 소비자. 세기만 한다."""

    def __init__(self) -> None:
        self.count = 0

    async def __call__(self, data: DataModel) -> None:
        self.count += 1


class SlowSender:
    """느린 소비자 (1): Sender 안에서 무거운 일을 한다. generator가 이것을 기다린다."""

    def __init__(self) -> None:
        self.done = 0

    async def __call__(self, data: DataModel) -> None:
        await asyncio.sleep(WORK)  # DB 쓰기 같은 무거운 일
        self.done += 1


class QueuedSender:
    """느린 소비자 (2): Sender는 큐에 넣기만 하고, 처리는 `run()` 태스크가 한다."""

    def __init__(self, maxsize: int = 3) -> None:
        self.queue: asyncio.Queue[DataModel] = asyncio.Queue(maxsize)
        self.done = 0
        self.dropped = 0

    async def __call__(self, data: DataModel) -> None:
        if self.queue.full():
            self.queue.get_nowait()  # 가장 오래된 것을 버린다
            self.dropped += 1
        self.queue.put_nowait(data)  # 기다리지 않고 바로 돌아온다

    async def run(self) -> None:
        while True:
            await self.queue.get()
            await asyncio.sleep(WORK)
            self.done += 1


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 느린 소비자를 자기 큐로 떼어 내기 ━━━━━━━━━━")

    log.info("----- 1. 느린 Sender와 빠른 소비자가 스테이지를 나눠 쓴다 -----")
    fast1, slow = Counter(), SlowSender()
    async with domain.subscribe(TickReq(), fast1) as a, domain.subscribe(TickReq(), slow) as b:
        await a.update({"BTC/USD"})
        await b.update({"BTC/USD"})
        await asyncio.sleep(WINDOW)
    log.info("받은 건수", fast=fast1.count, slow=slow.done)

    log.info("----- 2. 느린 소비자가 자기 큐로 받는다 -----")
    fast2, queued = Counter(), QueuedSender()
    worker = asyncio.create_task(queued.run())
    try:
        async with (
            domain.subscribe(TickReq(), fast2) as a,
            domain.subscribe(TickReq(), queued) as b,
        ):
            await a.update({"BTC/USD"})
            await b.update({"BTC/USD"})
            await asyncio.sleep(WINDOW)
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
    log.info("받은 건수", fast=fast2.count, slow=queued.done, dropped=queued.dropped)

    # 1단계의 빠른 소비자는 느린 Sender의 속도(1초에 몇 건)로 묶였다. 2단계는 제 속도로 받았다.
    assert fast2.count >= 3 * fast1.count, (fast1.count, fast2.count)
    assert queued.dropped > 0  # 다 처리하지 못한 것은 버렸다
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
