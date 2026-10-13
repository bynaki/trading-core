"""ex26: 소스 스테이지의 소비자가 밀릴 때 — 그 소비자만 `SenderOverflow`로 끊긴다

코어는 소비자마다 보내지 못한 데이터를 담아 두는 큐를 두고, 소스 generator는 거기에 넣기만
한다(ex25). 그 큐에는 상한이 있다. `Domain(sender_buffer=N)`건까지 쌓이면 코어는 데이터를 버리지
않고 **그 소비자의 구독 전체**를 끊어 `on_error`로 `StageFailed`를 알린다. 원인(`__cause__`)은
`SenderOverflow`다.

    소스 generator ─→ [A의 큐] → A  (제때 받는다)
                  └─→ [B의 큐] → B  (상대가 받지 않는 연결)
                       ↑ 5건이 차면 B만 끊긴다. A와 generator는 그대로 돈다.

이 예제의 B는 타임아웃을 걸지 않은 Sender다. 그래도 큐가 차면 떨어져 나간다. B가 빠지면 소스
generator의 심볼 합집합이 줄어 다시 시작한다(ex06). 끊긴 소비자는 `update()`로 다시 넣으면 새 큐로
다시 받는다.

`sender_buffer`는 `Domain`을 만들 때 정한다. 이 예제는 상한을 5건으로 둔 `Domain`을 따로 띄운다.

배우는 것
- 밀린 소비자는 버림 없이 끊기고, 끊기는 것은 그 소비자의 심볼 전부다.
- 다른 소비자와 소스 generator는 영향을 받지 않는다.
- 끊긴 소비자도 `update()`로 다시 넣으면 다시 받는다.

실행
    uv run examples/ex26_source_overflow.py

기대 출력 (줄 앞의 레벨은 뺐다)
    ex26: ----- 1. B의 연결이 막혔다 (sender_buffer=5) -----
    ex26.tick: generator 시작 {symbols=['BTC/USD', 'ETH/USD']}
    trading_core.routing: 데이터를 전송할 Sender가 없다 {symbol=ETH/USD}
    ex26: 끊겼다 B {symbols=['BTC/USD', 'ETH/USD'], cause=SenderOverflow}
    ex26.tick: generator 시작 {symbols=['BTC/USD']}
    ex26: 받은 건수 {a=20, b=1}
    ex26: ----- 2. B의 연결이 살아나 다시 넣는다 -----
    ex26.tick: generator 시작 {symbols=['BTC/USD', 'ETH/USD']}
    ex26: 받은 건수 {a=20, b=40}
    (건수는 실행마다 조금씩 다르다)

1단계에서 B는 첫 데이터에 묶인 채 5건이 더 쌓이자 끊겼다. B가 받은 것은 묶이기 전의 1건뿐이다.
A는 그동안 1초에 20건쯤 제때 받았다. B가 빠지자 합집합이 `{BTC/USD}`로 줄어 generator가 다시 섰다.
WARNING 줄은 B를 뗀 뒤 generator가 다시 서기 전에 옛 generator가 낸 `ETH/USD`다. 받을 소비자가 없다.

다음: ex27_derived_overflow.py — 파생 generator가 상위를 따라가지 못할 때
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    SenderOverflow,
    SourceRequest,
    StageFailed,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.05
SENDER_BUFFER = 5
"""소비자마다 쌓아 둘 수 있는 데이터 건수. 기본값은 1000이다."""
WINDOW = 1.0
"""단계마다 받는 시간."""

log = get_logger("ex26")
tick_log = get_logger("ex26.tick")


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
    tick_log.info("generator 시작", symbols=sorted(symbols))
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, seq=n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== 소비자 쪽 =====


class Counter:
    """제때 받는 소비자. 세기만 한다."""

    def __init__(self) -> None:
        self.count = 0

    async def __call__(self, data: DataModel) -> None:
        self.count += 1


class Connection:
    """WebSocket 같은 연결을 감싼 Sender. 연결이 막히면 `send`가 끝나지 않는다(타임아웃 없음)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.count = 0
        self.open = asyncio.Event()  # 꺼져 있으면 상대가 받지 않는다
        self.failures: list[StageFailed] = []

    async def __call__(self, data: DataModel) -> None:
        self.count += 1
        await self.open.wait()

    async def on_error(self, failed: StageFailed) -> None:
        self.failures.append(failed)
        cause = type(failed.__cause__).__name__
        log.warning(f"끊겼다 {self.name}", symbols=sorted(failed.symbols), cause=cause)


@contextlib.asynccontextmanager
async def small_domain() -> AsyncIterator[Domain]:
    """`sender_buffer`를 작게 둔 `Domain`을 띄우고 끝나면 내린다."""

    domain = Domain(sender_buffer=SENDER_BUFFER)
    await domain.start()
    try:
        yield domain
    finally:
        await domain.stop()


async def run_ex(domain: Domain) -> None:
    # `sender_buffer`는 `Domain`을 만들 때 정하므로 받은 `domain` 대신 작은 `Domain`을 쓴다.
    log.info("━━━━━━━━━━ 시작: 소스 스테이지의 소비자가 밀릴 때 ━━━━━━━━━━")
    async with small_domain() as small:
        a, b = Counter(), Connection("B")
        async with (
            small.subscribe(TickReq(), b, b.on_error) as sub_b,
            small.subscribe(TickReq(), a) as sub_a,
        ):
            log.info(f"----- 1. B의 연결이 막혔다 (sender_buffer={SENDER_BUFFER}) -----")
            await sub_b.update({"BTC/USD", "ETH/USD"})
            await sub_a.update({"BTC/USD"})  # 합집합이 그대로라 재시작하지 않는다
            await asyncio.sleep(WINDOW)
            log.info("받은 건수", a=a.count, b=b.count)
            assert [type(f.__cause__) for f in b.failures] == [SenderOverflow]
            assert b.failures[0].symbols == {"BTC/USD", "ETH/USD"}  # B의 심볼 전부
            assert b.count == 1  # 묶이기 전에 받은 1건
            assert a.count >= 10  # A는 B에 묶이지 않았다
            assert small.get_shared_symbols(TickReq().tr_content_id) == {"BTC/USD"}

            log.info("----- 2. B의 연결이 살아나 다시 넣는다 -----")
            b.open.set()
            a.count = b.count = 0
            await sub_b.update({"BTC/USD", "ETH/USD"})
            await asyncio.sleep(WINDOW)
            log.info("받은 건수", a=a.count, b=b.count)
            assert b.count >= 10 and len(b.failures) == 1
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
