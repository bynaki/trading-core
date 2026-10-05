"""ex24: binder가 심볼 하나만 거부할 때 — `SymbolRejected`

소스 generator는 심볼 합집합 하나로 돈다(ex05). 누군가 넣은 심볼 하나가 상장 폐지되었거나 오타라서
binder가 그냥 예외를 던지면, 같은 소스 스테이지를 쓰는 **모든 소비자가** 실패한다(ex17). 심볼 하나
때문에 그럴 일은 아니다. 이럴 때 binder는 `SymbolRejected(심볼들, 이유)`를 던진다.

    코어는 스테이지를 내리지 않는다. 그 심볼만 구독에서 빼고, 그 심볼을 구독한 소비자에게만
    알리고, 남은 심볼로 generator를 다시 띄운다.

거부는 그 소스 스테이지를 상위로 둔 파생·세션 요청에도 그 심볼만큼만 전해진다. 파생 소비자는
하위 표기 심볼로 받고, 세션은 그 상위 심볼을 쓰던 슬롯만 닫힌다(unbind된다).

    A: TickReq  {BTC/USD, DOGE/USD} ──────────────────┐
    B: PriceReq {DOGE, ETH} ─→ {DOGE/USD, ETH/USD} ───┼─ TickReq 소스 스테이지
    C: WatchReq {DOGE} ─→ 슬롯 DOGE ─→ DOGE/USD ──────┘   ← DOGE/USD를 거부한다

    → A는 {DOGE/USD}, B는 {DOGE}, C는 {DOGE}를 실패로 받는다.
      소스 스테이지는 {BTC/USD, ETH/USD}로 다시 돈다.

배우는 것
- generator에서 `SymbolRejected`를 던지면 그 심볼만 실패한다. 스테이지는 `@detached` 없이 남는다.
- 파생은 하위 표기로, 세션은 그 슬롯만 실패한다.
- 시작하자마자 거부해도 된다(없는 심볼 검사). 같이 넣은 다른 심볼은 받는다.
- 원인은 `StageFailed.__cause__`를 따라가면 binder가 던진 `SymbolRejected`가 나온다.

실행
    uv run examples/ex24_symbol_rejected.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex24: ----- 1. 도는 중에 DOGE/USD가 상장 폐지된다 -----
    ex24.tick: generator 시작 {symbols=['BTC/USD', 'DOGE/USD', 'ETH/USD']}
    trading_core.domain: 심볼이 실패해 구독에서 뺐다
      ... SymbolRejected: 심볼을 줄 수 없다. - ['DOGE/USD']: 상장 폐지
    ex24.tick: generator 시작 {symbols=['BTC/USD', 'ETH/USD']}
    ex24: 실패 통지 A {symbols=['DOGE/USD'], reason=상장 폐지}
    trading_core.domain: 심볼이 실패해 구독에서 뺐다      ← 파생 스테이지
      ...
    ex24: 실패 통지 B {symbols=['DOGE'], reason=상장 폐지}
    ex24.watch: unbind {symbol=DOGE}
    trading_core.domain: 세션 슬롯이 실패했다
      ...
    ex24: 실패 통지 C {symbols=['DOGE'], reason=상장 폐지}
    ex24: 공유 목록 {source=['BTC/USD', 'ETH/USD']}
    ex24: ----- 2. 오타 심볼 BTCC/USD로 구독한다 -----
    ex24.tick: generator 시작 {symbols=['BTC/USD', 'BTCC/USD']}
    trading_core.domain: 심볼이 실패해 구독에서 뺐다
      ... SymbolRejected: 심볼을 줄 수 없다. - ['BTCC/USD']: 거래소에 없는 심볼
    ex24.tick: generator 시작 {symbols=['BTC/USD']}
    ex24: 실패 통지 D {symbols=['BTCC/USD'], reason=거래소에 없는 심볼}
    (실패 통지 A와 그다음 ERROR 줄은 순서가 바뀔 때가 있다.)

`generator 시작`이 거부 직후 남은 심볼로 다시 나온다. `@detached`는 불리지 않았다 — 스테이지는
그대로다. 파생 스테이지도 내려가지 않고 DOGE만 뺐다.

거부된 심볼을 소비자가 다시 넣으면 binder가 또 거부한다. 다시 넣을지는 소비자가, 줄 수 있는지는
binder가 정한다. 지금 구독되지 않은 심볼만 거부하면 코어는 스테이지 전체의 실패로 본다. 같은
합집합으로 다시 띄우면 끝없이 되풀이되기 때문이다.

다음: ex25_slow_consumer.py — 느린 소비자가 공유 generator를 붙잡을 때
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    DerivedRequest,
    Domain,
    Receiver,
    Runnable,
    SessionRequest,
    SourceRequest,
    StageFailed,
    SymbolRejected,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2

LISTED = {"BTC/USD", "ETH/USD", "DOGE/USD"}
"""거래소에 상장된 심볼. 여기 없는 심볼은 generator가 시작하자마자 거부한다."""
DELISTED: set[str] = set()
"""도는 중에 상장 폐지된 심볼. generator가 다음 바퀴에 거부한다."""

log = get_logger("ex24")
tick_log = get_logger("ex24.tick")
watch_log = get_logger("ex24.watch")

GEN_STARTS: list[list[str]] = []
EVENTS: list[str] = []


# ===== binder 쪽 (1): 소스 요청 — 줄 수 없는 심볼을 거부한다 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """거부하면 이 generator는 끝난다. 남은 심볼로 다시 띄우는 것은 코어가 한다."""

    tick_log.info("generator 시작", symbols=sorted(symbols))
    GEN_STARTS.append(sorted(symbols))
    if unknown := symbols - LISTED:
        raise SymbolRejected(unknown, "거래소에 없는 심볼")
    n = 0
    while True:
        if delisted := symbols & DELISTED:
            raise SymbolRejected(delisted, "상장 폐지")
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=100.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


@tick.detached
async def _(ctx: TickReq):
    EVENTS.append("tick detached")


# ===== binder 쪽 (2): 파생 요청 — 하위 표기로 되돌린다 =====


class PriceReq(DerivedRequest):
    pass


class PriceData(DataModel):
    price: float


@PriceReq.require
def _(req: PriceReq, symbols: set[str]):
    return TickReq(), {f"{s}/USD" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    """거부를 모른다. 거부된 심볼을 하위 표기로 되돌려 알리는 것도 코어가 한다."""

    while True:
        tick_data = cast_model(await recv(), TickData)
        yield PriceData(symbol=tick_data.symbol.removesuffix("/USD"), price=tick_data.price)


# ===== binder 쪽 (3): 세션 요청 =====


class WatchReq(SessionRequest):
    pass


class Relay(Runnable[TickData, PriceData]):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: TickData) -> PriceData:
        return PriceData(symbol=self.symbol, price=input.price)


@initialize
def watch(req: WatchReq) -> WatchReq:
    return req


@watch
async def _(ctx: WatchReq, symbol: str):
    yield TickReq()(f"{symbol}/USD") | Relay(symbol)


@watch.unbind
async def _(ctx: WatchReq, symbol: str):
    watch_log.info("unbind", symbol=symbol)
    EVENTS.append(f"unbind {symbol}")


# ===== 소비자 쪽 =====


def rejected_reason(failed: StageFailed) -> str:
    """`__cause__`를 따라가 binder가 던진 `SymbolRejected`의 이유를 꺼낸다."""

    cause = failed.__cause__
    while isinstance(cause, StageFailed):  # 파생·세션은 상위의 StageFailed를 거친다
        cause = cause.__cause__
    return cause.reason if isinstance(cause, SymbolRejected) else ""


class Consumer:
    def __init__(self, name: str) -> None:
        self.name = name
        self.received: list[str] = []
        self.failures: list[StageFailed] = []

    async def __call__(self, data: DataModel) -> None:
        self.received.append(data.symbol)

    async def on_error(self, failed: StageFailed) -> None:
        self.failures.append(failed)
        reason = rejected_reason(failed)
        log.warning(f"실패 통지 {self.name}", symbols=sorted(failed.symbols), reason=reason)

    async def wait(self, done) -> None:
        async with asyncio.timeout(3):
            while not done():
                await asyncio.sleep(0.05)


async def delisting(domain: Domain) -> None:
    log.info("----- 1. 도는 중에 DOGE/USD가 상장 폐지된다 -----")
    source_id = TickReq().tr_content_id
    a, b, c = Consumer("A"), Consumer("B"), Consumer("C")

    async with (
        domain.subscribe(TickReq(), a, a.on_error) as sub_a,
        domain.subscribe(PriceReq(), b, b.on_error) as sub_b,
        domain.subscribe(WatchReq(), c, c.on_error) as sub_c,
    ):
        await sub_a.update({"BTC/USD", "DOGE/USD"})
        await sub_b.update({"DOGE", "ETH"})
        await sub_c.update({"DOGE"})
        await a.wait(lambda: "DOGE/USD" in a.received)

        DELISTED.add("DOGE/USD")
        await a.wait(lambda: a.failures and b.failures and c.failures)
        log.info("공유 목록", source=sorted(domain.get_shared_symbols(source_id)))

        assert a.failures[0].symbols == {"DOGE/USD"}
        assert b.failures[0].symbols == {"DOGE"}  # 파생 소비자는 하위 표기로
        assert c.failures[0].symbols == {"DOGE"}  # 세션은 그 슬롯만
        assert rejected_reason(b.failures[0]) == "상장 폐지"
        assert EVENTS == ["unbind DOGE"]  # 세션 슬롯은 닫히고 unbind된다. 스테이지는 detach 안 됨
        assert domain.get_shared_symbols(source_id) == {"BTC/USD", "ETH/USD"}

        # 남은 심볼로 다시 돈다. A는 BTC/USD, B는 ETH를 계속 받는다.
        a_before, b_before = a.received.count("BTC/USD"), b.received.count("ETH")
        await a.wait(lambda: a.received.count("BTC/USD") > a_before)
        await b.wait(lambda: b.received.count("ETH") > b_before)
        assert GEN_STARTS[-1] == ["BTC/USD", "ETH/USD"]


async def unknown_symbol(domain: Domain) -> None:
    log.info("----- 2. 오타 심볼 BTCC/USD로 구독한다 -----")
    d = Consumer("D")
    async with domain.subscribe(TickReq(), d, d.on_error) as sub:
        await sub.update({"BTC/USD", "BTCC/USD"})
        await d.wait(lambda: d.failures and "BTC/USD" in d.received)

        assert d.failures[0].symbols == {"BTCC/USD"}
        assert rejected_reason(d.failures[0]) == "거래소에 없는 심볼"
        assert "BTC/USD" in d.received  # 같이 넣은 심볼은 받는다


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: binder가 심볼 하나만 거부할 때 ━━━━━━━━━━")
    DELISTED.clear()
    GEN_STARTS.clear()
    EVENTS.clear()
    await delisting(domain)
    await unknown_symbol(domain)
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
