"""ex12: 세션의 정리 — 심볼이 빠질 때 `unbind`, 구독이 끝날 때 `detached`

세션 요청에도 정리 지점이 둘 있다. ex03의 두 정리 지점과 짝을 이룬다.

| 언제 | 소스·파생 요청 | 세션 요청 |
| --- | --- | --- |
| 심볼이 빠질 때 | generator `finally` (재시작) | `@x.unbind(ctx, symbol)` — 그 심볼만 |
| 구독이 끝날 때 | `@x.detached(ctx)` | `@x.detached(ctx)` |

소스·파생 스테이지는 심볼이 하나만 바뀌어도 generator 전체를 다시 띄운다(ex06). 세션은 심볼마다
슬롯이 따로라 **바뀐 심볼만** 건드린다. 새 심볼은 bind하고, 빠진 심볼은 unbind하고, 그대로인 심볼의
슬롯(과 그 안의 상태)은 그대로 둔다.

bind로 연 심볼은 어떻게 닫히든(`update()`로 빠지든, 구독이 끝나든) unbind가 **정확히 한 번**
불린다. 그래서 bind에서 연 심볼별 자원(구독 메시지, 심볼별 파일 등)은 unbind에서 닫으면 된다.

배우는 것
- `@x.unbind`는 빠진 심볼 하나마다 불린다. `update()`가 unbind가 끝날 때까지 기다리므로,
  `update()`가 돌아온 직후 결과를 확인할 수 있다.
- 남아 있는 심볼은 다시 bind되지 않는다(BTC의 단계 객체가 받은 건수가 끊기지 않고 이어진다).
- 구독이 끝나면 열린 심볼을 모두 unbind한 뒤 `@x.detached`를 한 번 부른다.

실행
    uv run examples/ex12_unbind.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex12: ----- 1. update({'BTC'}) -----
    ex12.watch: init
    ex12.watch: bind {symbol=BTC}
    ex12: ----- 2. update({'BTC', 'ETH'}): ETH만 bind -----
    ex12.watch: bind {symbol=ETH}
    ex12: ----- 3. update({'ETH'}): BTC만 unbind -----
    ex12.watch: unbind {symbol=BTC, seen=6}
    ex12: ----- 4. 블록을 벗어난다 -----
    ex12.watch: unbind {symbol=ETH, seen=5}
    ex12.watch: detached {open=[]}
    (seen은 실행마다 조금씩 다르다)

다음: ex13_not_shared.py — 내용이 같아도 세션은 나눠 쓰지 않는다
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    Runnable,
    SessionRequest,
    SourceRequest,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
BASE_PRICE = {"BTC/USD": 100.0, "ETH/USD": 200.0}

log = get_logger("ex12")
watch_log = get_logger("ex12.watch")

EVENTS: list[str] = []
"""세션 콜백이 불린 차례."""


# ===== binder 쪽 (1): 소스 요청 =====


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


# ===== binder 쪽 (2): 세션 요청 — 심볼별 자원을 열고 닫는다 =====


class WatchReq(SessionRequest):
    pass


class WatchData(DataModel):
    price: float


class Count(Runnable[TickData, WatchData]):
    """심볼 하나의 단계. 지나간 건수를 센다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.seen = 0

    async def invoke(self, input: TickData) -> WatchData:
        self.seen += 1
        return WatchData(symbol=self.symbol, price=input.price)


class WatchCtx:
    """세션 컨텍스트. 지금 열려 있는 심볼과 그 단계 객체를 들고 있다."""

    def __init__(self) -> None:
        self.open: dict[str, Count] = {}


@initialize
def watch(req: WatchReq) -> WatchCtx:
    watch_log.info("init")
    EVENTS.append("init")
    return WatchCtx()


@watch
async def _(ctx: WatchCtx, symbol: str):
    """bind: 심볼별 자원을 연다."""

    watch_log.info("bind", symbol=symbol)
    EVENTS.append(f"bind {symbol}")
    step = ctx.open[symbol] = Count(symbol)
    yield TickReq()(f"{symbol}/USD") | step


@watch.unbind
async def _(ctx: WatchCtx, symbol: str):
    """unbind: bind에서 연 그 심볼의 자원을 닫는다."""

    step = ctx.open.pop(symbol)
    watch_log.info("unbind", symbol=symbol, seen=step.seen)
    EVENTS.append(f"unbind {symbol}")


@watch.detached
async def _(ctx: WatchCtx):
    """detached: 구독 전체의 자원을 닫는다. 이때 열린 심볼은 이미 모두 unbind되었다."""

    watch_log.info("detached", open=sorted(ctx.open))
    EVENTS.append("detached")


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 세션의 정리 — unbind와 detached ━━━━━━━━━━")
    EVENTS.clear()
    received: list[str] = []

    async def collect(data: DataModel) -> None:
        received.append(data.symbol)

    async with domain.subscribe(WatchReq(), collect) as sub:
        log.info("----- 1. update({'BTC'}) -----")
        await sub.update({"BTC"})
        await asyncio.sleep(0.5)

        log.info("----- 2. update({'BTC', 'ETH'}): ETH만 bind -----")
        await sub.update({"BTC", "ETH"})
        await asyncio.sleep(0.5)

        log.info("----- 3. update({'ETH'}): BTC만 unbind -----")
        await sub.update({"ETH"})
        assert EVENTS[-1] == "unbind BTC"  # update()가 unbind를 기다렸다
        await asyncio.sleep(0.3)

        log.info("----- 4. 블록을 벗어난다 -----")

    assert EVENTS == [
        "init",
        "bind BTC",
        "bind ETH",  # BTC는 다시 bind되지 않았다
        "unbind BTC",
        "unbind ETH",  # 구독이 끝날 때 남은 심볼을 unbind한 뒤
        "detached",  # 마지막에 한 번
    ], EVENTS
    # BTC 슬롯은 2단계에서 끊기지 않았다 — 1·2단계 내내 받았다.
    assert received.count("BTC") >= 4
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
