"""ex25: 느린 소비자 — 남을 붙잡지 않고, 밀리면 떨어져 나간다

소스 generator는 데이터를 하나 yield하면 그 심볼을 구독한 소비자 모두에게 나눠 준다. 소비자의
Sender가 느리다고 generator가 그것을 기다리면, 같은 스테이지를 나눠 쓰는 빠른 소비자도 덩달아
늦어진다. 그래서 코어는 소비자마다 **보내지 못한 데이터를 쌓아 두는 큐**를 두고 거기에 넣기만 한다.

    generator ─ yield ─→ [빠른 소비자의 큐] → 빠른 Sender  (곧 끝남)
                     └─→ [느린 소비자의 큐] → 느린 Sender  (0.3초)  ← 이 큐에만 쌓인다

느림은 그 소비자의 큐에만 쌓인다. 큐가 `Domain(sender_buffer=...)`건(기본 1000)까지 차면 코어는
데이터를 버리지 않고 그 소비자만 `SenderOverflow`로 끊는다(`on_error`로 `StageFailed`). 데이터를
버려도 되는지는 코어가 모르기 때문이다. 큐가 차서 끊기는 모습은 소스·파생·세션·`stream()`별로
ex26~29가 보인다. 막힌 연결을 얼마나 기다릴지는 Sender가 정한다. Sender 안에서 타임아웃을 걸어
던지면 큐가 차기를 기다리지 않고 그 소비자만 곧바로 떨어진다.

배우는 것
- Sender가 느려도 같은 소스 스테이지의 다른 소비자는 제 속도로 받는다.
- 막힌 연결은 Sender 안에서 타임아웃을 걸어 던진다. 그 소비자만 떨어진다.
- 최신 것만 의미 있으면 소비자가 자기 큐로 받아 오래된 것을 직접 버린다. 그러면 끊기지 않는다.

실행
    uv run examples/ex25_slow_consumer.py

기대 출력 (줄 앞의 레벨은 뺐다)
    ex25: ----- 1. 느린 Sender와 빠른 소비자가 스테이지를 나눠 쓴다 -----
    ex25: 받은 건수 {fast=20, slow=3}
    ex25: ----- 2. 막힌 연결은 Sender 안의 타임아웃으로 끊는다 -----
    ex25: 끊겼다 {symbols=['BTC/USD'], cause=TimeoutError}
    ex25: 받은 건수 {fast=20}
    ex25: ----- 3. 최신 것만 필요하면 자기 큐로 받아 버린다 -----
    ex25: 받은 건수 {fast=20, slow=3, dropped=13}
    (건수는 실행마다 조금씩 다르다)

1단계의 빠른 소비자는 느린 Sender와 상관없이 1초에 20건쯤 받았다. 느린 소비자는 그사이 쌓인
것을 처리하다가 구독을 끊을 때 남은 것을 잃는다. 2단계는 응답이 없는 연결을 0.3초 만에 끊었다.
3단계의 느린 소비자는 오래된 가격을 스스로 버려 코어의 큐가 차지 않으므로 끊기지 않는다.

다음: ex26_source_overflow.py — 소스 스테이지의 소비자가 밀릴 때
"""

import asyncio
import contextlib
from pathlib import Path

from trading_core import DataModel, Domain, SourceRequest, StageFailed, initialize
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.05
WORK = 0.3
"""느린 소비자가 데이터 하나를 처리하는 시간."""
SEND_TIMEOUT = 0.3
"""Sender가 막힌 연결을 기다리는 시간."""
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
    """느린 소비자: Sender 안에서 무거운 일을 한다."""

    def __init__(self) -> None:
        self.done = 0

    async def __call__(self, data: DataModel) -> None:
        await asyncio.sleep(WORK)  # DB 쓰기 같은 무거운 일
        self.done += 1


class HungSender:
    """응답이 없는 연결을 감싼 Sender. 전송을 `SEND_TIMEOUT`까지만 기다리고 던진다."""

    def __init__(self) -> None:
        self._never = asyncio.Event()  # 상대가 받지 않는 연결

    async def __call__(self, data: DataModel) -> None:
        async with asyncio.timeout(SEND_TIMEOUT):
            await self._never.wait()


class QueuedSender:
    """최신 것만 의미 있는 느린 소비자: 자기 큐에 넣기만 하고, 처리는 `run()` 태스크가 한다."""

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


class Disconnects:
    """`on_error`로 받은 실패를 남긴다."""

    def __init__(self) -> None:
        self.received: list[StageFailed] = []

    async def __call__(self, failed: StageFailed) -> None:
        self.received.append(failed)
        log.info("끊겼다", symbols=sorted(failed.symbols), cause=type(failed.__cause__).__name__)


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 느린 소비자 ━━━━━━━━━━")

    log.info("----- 1. 느린 Sender와 빠른 소비자가 스테이지를 나눠 쓴다 -----")
    fast1, slow = Counter(), SlowSender()
    async with domain.subscribe(TickReq(), fast1) as a, domain.subscribe(TickReq(), slow) as b:
        await a.update({"BTC/USD"})
        await b.update({"BTC/USD"})
        await asyncio.sleep(WINDOW)
    log.info("받은 건수", fast=fast1.count, slow=slow.done)
    assert fast1.count >= 3 * slow.done, (fast1.count, slow.done)  # 느린 쪽에 묶이지 않았다

    log.info("----- 2. 막힌 연결은 Sender 안의 타임아웃으로 끊는다 -----")
    fast2, hung, disconnects = Counter(), HungSender(), Disconnects()
    async with (
        domain.subscribe(TickReq(), fast2) as a,
        domain.subscribe(TickReq(), hung, disconnects) as b,
    ):
        await a.update({"BTC/USD"})
        await b.update({"BTC/USD"})
        await asyncio.sleep(WINDOW)
    log.info("받은 건수", fast=fast2.count)
    assert [type(f.__cause__) for f in disconnects.received] == [TimeoutError]

    log.info("----- 3. 최신 것만 필요하면 자기 큐로 받아 버린다 -----")
    fast3, queued, disconnects = Counter(), QueuedSender(), Disconnects()
    worker = asyncio.create_task(queued.run())
    try:
        async with (
            domain.subscribe(TickReq(), fast3) as a,
            domain.subscribe(TickReq(), queued, disconnects) as b,
        ):
            await a.update({"BTC/USD"})
            await b.update({"BTC/USD"})
            await asyncio.sleep(WINDOW)
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
    log.info("받은 건수", fast=fast3.count, slow=queued.done, dropped=queued.dropped)
    assert queued.dropped > 0  # 다 처리하지 못한 것은 스스로 버렸다
    assert disconnects.received == []  # 그래서 끊기지 않았다
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
