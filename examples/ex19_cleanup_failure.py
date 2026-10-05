"""ex19: 정리 콜백이 던질 때 — 정리는 끝까지 하고 로그만 남긴다

`@detached`·`@x.unbind`·generator `finally` 같은 정리 콜백도 던질 수 있다. 연결을 닫다가 이미 끊겨
있었다든가 하는 일이다. 정리 콜백 하나가 던졌다고 나머지 정리를 건너뛰면 자원이 샌다. 그래서 코어는
이렇게 한다.

    정리 콜백이 던져도 **나머지 정리를 끝까지 한다**(던지지 않은 형제 콜백도 다 부른다).
    실패는 ERROR 로그로만 남기고, `update()`나 구독을 닫는 쪽(`async with`)에 올리지 않는다.

정리 실패는 소비자의 실패도 아니다. 소비자는 이미 떠나는 중이므로 `on_error`로 알리지 않는다.

이 예제는 일부러 두 군데서 던진다.

    세션 WatchReq {BTC, ETH}   unbind BTC가 던진다 → unbind ETH·detached는 그래도 불린다
        └→ TickReq 소스 스테이지   detached가 던진다 → 그래도 스테이지는 내려간다

배우는 것
- 정리 콜백이 던져도 `async with`는 예외 없이 빠져나온다.
- 같이 불리는 정리 콜백(여기선 unbind BTC·ETH)은 하나가 던져도 모두 불린다.
- 정리 실패는 `on_error`로 오지 않는다. 남는 것은 `trading_core.domain`의 ERROR 로그다.

실행
    uv run examples/ex19_cleanup_failure.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex19: ----- 블록을 벗어난다: 정리 콜백 둘이 던진다 -----
    ex19.watch: unbind {symbol=ETH}
    ex19.watch: unbind {symbol=BTC}
    trading_core.domain: 정리 콜백이 실패했다 {callback=unbind}
    Traceback (most recent call last):
      ...
    RuntimeError: BTC 기록 파일을 닫다가 실패했다
    ex19.tick: detached
    trading_core.domain: 정리 콜백이 실패했다 {callback=detach}
    Traceback (most recent call last):
      ...
    RuntimeError: 연결을 닫다가 실패했다
    ex19.watch: detached
    ex19: async with가 끝났다 {raised=None, on_error=0}
    (unbind 두 줄의 순서는 실행마다 바뀐다. 함께 돌기 때문이다.)

세션의 `detached`보다 소스 스테이지의 `detached`가 먼저 불린다. 세션이 슬롯을 닫으며 상위 구독을
먼저 떼고, 그때 소스 스테이지의 마지막 구독이 빠지기 때문이다.

다음: ex20_stream_failure.py — `stream()`으로 받을 때의 실패
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    Runnable,
    SessionRequest,
    SourceRequest,
    StageFailed,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2

log = get_logger("ex19")
tick_log = get_logger("ex19.tick")
watch_log = get_logger("ex19.watch")

EVENTS: list[str] = []
"""불린 정리 콜백."""


# ===== binder 쪽 (1): 소스 요청 — detached가 던진다 =====


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


@tick.detached
async def _(ctx: TickReq):
    tick_log.info("detached")
    EVENTS.append("tick detached")
    raise RuntimeError("연결을 닫다가 실패했다")


# ===== binder 쪽 (2): 세션 요청 — BTC의 unbind가 던진다 =====


class WatchReq(SessionRequest):
    pass


class WatchData(DataModel):
    price: float


class Relay(Runnable[TickData, WatchData]):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: TickData) -> WatchData:
        return WatchData(symbol=self.symbol, price=input.price)


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
    if symbol == "BTC":
        raise RuntimeError("BTC 기록 파일을 닫다가 실패했다")


@watch.detached
async def _(ctx: WatchReq):
    watch_log.info("detached")
    EVENTS.append("watch detached")


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 정리 콜백이 던질 때 ━━━━━━━━━━")
    EVENTS.clear()
    failures: list[StageFailed] = []
    count = 0

    async def collect(data: DataModel) -> None:
        nonlocal count
        count += 1

    async def on_error(failed: StageFailed) -> None:
        failures.append(failed)

    raised: Exception | None = None
    try:
        async with domain.subscribe(WatchReq(), collect, on_error) as sub:
            await sub.update({"BTC"})
            await sub.update({"BTC", "ETH"})
            await asyncio.sleep(0.5)
            log.info("----- 블록을 벗어난다: 정리 콜백 둘이 던진다 -----")
    except Exception as exc:
        raised = exc
    log.info("async with가 끝났다", raised=repr(raised), on_error=len(failures))

    assert count > 0
    assert raised is None  # 정리 실패는 호출자에게 올라오지 않는다
    assert not failures  # 소비자의 실패도 아니다
    # 던진 unbind BTC의 형제 unbind ETH도, 그 뒤의 detached도 모두 불렸다.
    assert sorted(EVENTS) == ["tick detached", "unbind BTC", "unbind ETH", "watch detached"]
    assert domain.get_shared_symbols(TickReq().tr_content_id) == set()  # 스테이지도 내려갔다
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
