"""ex28: 세션의 슬롯이 밀릴 때 — 그 심볼만 `SenderOverflow`로 끊긴다

세션은 심볼마다 슬롯 하나를 열고, 슬롯마다 상위 데이터를 받아 두는 큐와 태스크가 있다(ex11). 슬롯
태스크는 큐에서 꺼내 파이프라인을 거친 뒤 소비자 Sender로 보낸다. 상위 소스 generator는 슬롯 큐에
넣기만 하고 기다리지 않는다.

    소스 generator ─→ [BTC 슬롯 큐] → 파이프라인 → 소비자
                  └─→ [ETH 슬롯 큐] → 파이프라인(무거움) → 소비자
                       ↑ 5건이 차면 ETH 슬롯만 실패한다

슬롯 큐에도 상한(`sender_buffer`)이 있다. 파이프라인이 무겁거나 소비자 Sender가 막혀 큐가 차면,
코어는 데이터를 버리지 않고 **그 슬롯(하위 표기 심볼 하나)만** 내리고 알린다. 세션 출력은 놓치면 안
되는 신호일 수 있으므로 버리지 않는다. 그 심볼은 unbind되고, 다른 심볼의 슬롯은 그대로 돈다.

소비자 Sender가 막히면 모든 슬롯이 같은 Sender를 기다리므로 슬롯마다 차례로 차서 모두 끊긴다.

`sender_buffer`는 `Domain`을 만들 때 정한다. 이 예제는 상한을 5건으로 둔 `Domain`을 따로 띄운다.

배우는 것
- 세션은 슬롯 단위로 끊긴다. 밀린 심볼만 실패하고 그 심볼만 unbind된다.
- 파이프라인이 무거워 밀려도, 소비자가 막혀 밀려도 같다.
- 실패는 하위 표기 심볼(`ETH`)로 온다.

실행
    uv run examples/ex28_session_overflow.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex28: ----- 1. ETH의 분석만 한 건에 0.2초 걸린다 (sender_buffer=5) -----
    ex28.signal: bind {symbol=BTC}
    ex28.signal: bind {symbol=ETH}
    ex28.signal: unbind {symbol=ETH}
    trading_core.domain: 세션 슬롯이 실패했다 {"stage": "SignalReq@...", "symbols": ["ETH"]}
      ... SenderOverflow: 처리하지 못한 데이터가 5건 쌓였다.
    ex28: 끊겼다 A {symbols=['ETH'], cause=SenderOverflow}
    ex28: 받은 건수 {btc=20, eth=1}
    ex28.signal: unbind {symbol=BTC}
    ex28: ----- 2. 소비자 B의 연결이 막혔다 -----
    ex28.signal: bind {symbol=BTC}
    ex28.signal: bind {symbol=XRP}
    ex28.signal: unbind {symbol=BTC}
    trading_core.domain: 세션 슬롯이 실패했다 {"stage": "SignalReq@...", "symbols": ["BTC"]}
      ...
    ex28.signal: unbind {symbol=XRP}
    trading_core.domain: 세션 슬롯이 실패했다 {"stage": "SignalReq@...", "symbols": ["XRP"]}
      ...
    ex28: 끊겼다 B {symbols=['BTC'], cause=SenderOverflow}
    ex28: 끊겼다 B {symbols=['XRP'], cause=SenderOverflow}
    (BTC의 건수는 실행마다 조금씩 다르다)

1단계에서 ETH 슬롯은 첫 분석(0.2초)을 끝내 1건을 보냈지만, 다음 분석을 하는 동안 5건이 쌓여 끊겼다.
그동안 BTC 슬롯은 1초에 20건쯤 제때 받았다. 1단계 끝의 `unbind BTC`는 구독을 마치며 남은 슬롯을
닫은 것이다. 2단계에서는 모든 슬롯이 막힌 B를 기다리므로 BTC와 XRP가 각각 끊겼다.

다음: ex29_stream_overflow.py — `stream()`을 읽는 쪽이 밀릴 때
"""

import asyncio
import contextlib
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    Runnable,
    SenderOverflow,
    SessionRequest,
    SourceRequest,
    StageFailed,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.05
WORK = 0.2
"""무거운 분석 한 건에 걸리는 시간."""
HEAVY = {"ETH"}
"""분석이 무거운 심볼(하위 표기)."""
SENDER_BUFFER = 5
"""슬롯마다 처리하지 못한 데이터를 쌓아 둘 수 있는 건수. 기본값은 1000이다."""
WINDOW = 1.0
"""단계마다 받는 시간."""

log = get_logger("ex28")
signal_log = get_logger("ex28.signal")


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
            yield TickData(symbol=symbol, price=100.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 세션 요청 — 심볼마다 분석 =====


class SignalReq(SessionRequest):
    pass


class SignalData(DataModel):
    price: float


class Analyze(Runnable[TickData, SignalData]):
    """심볼 하나의 분석 단계. `HEAVY` 심볼은 오래 걸린다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol  # 하위 표기

    async def invoke(self, input: TickData) -> SignalData | None:
        if self.symbol in HEAVY:
            await asyncio.sleep(WORK)
        return SignalData(symbol=self.symbol, price=input.price)


@initialize
def signal(req: SignalReq) -> SignalReq:
    return req


@signal
async def _(ctx: SignalReq, symbol: str):
    signal_log.info("bind", symbol=symbol)
    yield TickReq()(f"{symbol}/USD") | Analyze(symbol)


@signal.unbind
async def _(ctx: SignalReq, symbol: str):
    signal_log.info("unbind", symbol=symbol)


# ===== 소비자 쪽 =====


class Consumer:
    """심볼별 받은 건수와 실패를 남기는 소비자. `open`이 꺼져 있으면 연결이 막힌 것이다."""

    def __init__(self, name: str, *, open: bool = True) -> None:
        self.name = name
        self.counts: Counter[str] = Counter()
        self.failures: list[StageFailed] = []
        self.open = asyncio.Event()
        if open:
            self.open.set()

    async def __call__(self, data: DataModel) -> None:
        self.counts[data.symbol] += 1
        await self.open.wait()

    async def on_error(self, failed: StageFailed) -> None:
        self.failures.append(failed)

    def log_failures(self) -> None:
        for failed in sorted(self.failures, key=lambda f: sorted(f.symbols)):
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
    log.info("━━━━━━━━━━ 시작: 세션의 슬롯이 밀릴 때 ━━━━━━━━━━")
    async with small_domain() as small:
        log.info(
            f"----- 1. ETH의 분석만 한 건에 {WORK}초 걸린다 (sender_buffer={SENDER_BUFFER}) -----"
        )
        a = Consumer("A")
        async with small.subscribe(SignalReq(), a, a.on_error) as sub:
            await sub.update({"BTC"})  # bind 순서가 실행마다 같도록 하나씩 넣는다
            await sub.update({"BTC", "ETH"})
            await asyncio.sleep(WINDOW)
            a.log_failures()
            log.info("받은 건수", btc=a.counts["BTC"], eth=a.counts["ETH"])
            [failed] = a.failures
            assert failed.symbols == {"ETH"}  # 하위 표기 심볼 하나만
            assert isinstance(failed.__cause__, SenderOverflow)
            assert a.counts["BTC"] >= 10 and a.counts["ETH"] <= 1
            assert small.get_shared_symbols(TickReq().tr_content_id) == {"BTC/USD"}

        log.info("----- 2. 소비자 B의 연결이 막혔다 -----")
        b = Consumer("B", open=False)
        async with small.subscribe(SignalReq(), b, b.on_error) as sub:
            await sub.update({"BTC"})
            await sub.update({"BTC", "XRP"})
            await asyncio.sleep(WINDOW)
            b.log_failures()
            assert sorted(sorted(f.symbols) for f in b.failures) == [["BTC"], ["XRP"]]
            assert all(isinstance(f.__cause__, SenderOverflow) for f in b.failures)
            assert small.get_shared_symbols(TickReq().tr_content_id) == set()
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
