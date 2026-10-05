"""ex22: 세션 요청의 실패 — 그 심볼 하나만 실패한다

세션은 심볼마다 슬롯이 따로다(ex11). 그래서 실패도 대개 **그 심볼 하나**로 끝난다. 세션에서 던질 수
있는 곳은 셋이다.

| 어디서 | 실패하는 심볼 | 언제 알려지나 |
| --- | --- | --- |
| init 콜백 | 그 `update()`가 넣으려던 심볼 모두 | `update()`가 돌아올 때 이미 |
| bind 콜백 | 그 심볼 | `update()`가 돌아올 때 이미 |
| 파이프라인 단계 | 그 심볼(슬롯이 닫히고 unbind된다) | 데이터가 지나가다 던질 때 |

세션의 init은 `subscribe()`가 아니라 **첫 `update()`**에서 불린다. init이 던지면 컨텍스트가 없으니
그 `update()`의 심볼이 모두 실패하고, 다음 `update()`가 init부터 다시 한다. init·bind 실패는
`update()`가 그 자리에서 알리므로 기다릴 필요가 없다. 그래도 `update()`는 던지지 않는다.

상위 소스 스테이지가 실패하면 그 상위에 붙은 슬롯의 심볼(하위 표기)만 실패로 온다. 소스 쪽 실패는
ex17과 같으므로 여기서는 세션 자신이 던지는 경우만 본다.

배우는 것
- 세션 init 실패: 요청한 심볼 모두가 실패하고, 다음 `update()`가 init을 다시 한다.
- bind·파이프라인 단계 실패: 그 심볼만 실패하고 다른 심볼은 계속 받는다.
- 단계가 던져 닫힌 슬롯도 bind했던 심볼이므로 unbind가 불린다.

실행
    uv run examples/ex22_session_failure.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex22: ----- 1. update({'BTC'}): init이 던진다 -----
    ex22.watch: init {no=1}
    trading_core.domain: init 콜백이 실패했다
      ...
    ex22: 실패 통지 {symbols=['BTC'], cause=OSError: 세션 저장소를 열지 못했다}
    ex22: ----- 2. update({'BTC'}) 다시: init부터 다시 한다 -----
    ex22.watch: init {no=2}
    ex22.watch: bind {symbol=BTC}
    ex22: ----- 3. update({'BTC', 'DOGE'}): DOGE의 bind가 던진다 -----
    ex22.watch: bind {symbol=DOGE}
    trading_core.domain: 심볼을 bind하지 못했다 {stage=WatchReq@..., symbol=DOGE}
      ...
    ex22: 실패 통지 {symbols=['DOGE'], cause=ValueError: 지원하지 않는 코인: DOGE}
    ex22: ----- 4. update({'BTC', 'ETH'}): ETH의 파이프라인 단계가 던진다 -----
    ex22.watch: bind {symbol=ETH}
    ex22.watch: unbind {symbol=ETH}
    trading_core.domain: 세션 슬롯이 실패했다
      ...
    ex22: 실패 통지 {symbols=['ETH'], cause=ValueError: 가격이 이상하다: -1.0}
    ex22: BTC는 계속 받는다 {btc=2}
    ex22.watch: unbind {symbol=BTC}
    (btc 건수는 실행마다 조금씩 다르다)

1·3단계의 `실패 통지`는 그다음 단계 줄보다 먼저 나온다. `update()`가 돌아오기 전에 이미 알렸다.

다음: ex23_always_failure.py — always 파이프라인의 실패
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
PRICE = {"BTC/USD": 100.0, "ETH/USD": -1.0}
"""ETH 피드는 고장 나서 음수 가격을 보낸다."""
LISTED = {"BTC", "ETH"}
"""bind할 수 있는 코인. 여기 없는 코인은 bind가 거부한다."""

log = get_logger("ex22")
watch_log = get_logger("ex22.watch")

INIT_TRIES: list[int] = []
EVENTS: list[str] = []


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
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=PRICE[symbol])
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 세션 요청 — 세 군데서 던질 수 있다 =====


class WatchReq(SessionRequest):
    pass


class WatchData(DataModel):
    price: float


class Check(Runnable[TickData, WatchData]):
    """파이프라인 단계. 가격이 이상하면 던진다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: TickData) -> WatchData:
        if input.price <= 0:
            raise ValueError(f"가격이 이상하다: {input.price}")
        return WatchData(symbol=self.symbol, price=input.price)


@initialize
def watch(req: WatchReq) -> WatchReq:
    """첫 시도는 저장소를 열지 못해 던진다."""

    INIT_TRIES.append(len(INIT_TRIES) + 1)
    watch_log.info("init", no=INIT_TRIES[-1])
    if INIT_TRIES[-1] == 1:
        raise OSError("세션 저장소를 열지 못했다")
    return req


@watch
async def _(ctx: WatchReq, symbol: str):
    watch_log.info("bind", symbol=symbol)
    if symbol not in LISTED:
        raise ValueError(f"지원하지 않는 코인: {symbol}")
    yield TickReq()(f"{symbol}/USD") | Check(symbol)


@watch.unbind
async def _(ctx: WatchReq, symbol: str):
    watch_log.info("unbind", symbol=symbol)
    EVENTS.append(f"unbind {symbol}")


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 세션 요청의 실패 ━━━━━━━━━━")
    INIT_TRIES.clear()
    EVENTS.clear()
    failures: list[StageFailed] = []
    received: list[str] = []

    async def collect(data: DataModel) -> None:
        received.append(data.symbol)

    async def on_error(failed: StageFailed) -> None:
        failures.append(failed)
        log.warning("실패 통지", symbols=sorted(failed.symbols), cause=failed.cause)

    async with domain.subscribe(WatchReq(), collect, on_error) as sub:
        log.info("----- 1. update({'BTC'}): init이 던진다 -----")
        await sub.update({"BTC"})
        # 기다리지 않아도 이미 알려져 있다.
        assert [f.symbols for f in failures] == [{"BTC"}]

        log.info("----- 2. update({'BTC'}) 다시: init부터 다시 한다 -----")
        await sub.update({"BTC"})
        assert INIT_TRIES == [1, 2]

        log.info("----- 3. update({'BTC', 'DOGE'}): DOGE의 bind가 던진다 -----")
        await sub.update({"BTC", "DOGE"})
        assert failures[-1].symbols == {"DOGE"}
        assert "unbind DOGE" not in EVENTS  # bind가 끝나지 않았으니 unbind할 것도 없다

        log.info("----- 4. update({'BTC', 'ETH'}): ETH의 파이프라인 단계가 던진다 -----")
        await sub.update({"BTC", "ETH"})
        async with asyncio.timeout(3):
            while len(failures) < 3:
                await asyncio.sleep(0.05)
        assert failures[-1].symbols == {"ETH"}
        assert failures[-1].cause == "ValueError: 가격이 이상하다: -1.0"
        assert EVENTS == ["unbind ETH"]  # bind했던 심볼이라 unbind로 짝을 맞춘다

        btc_before = received.count("BTC")
        await asyncio.sleep(0.5)
        log.info("BTC는 계속 받는다", btc=received.count("BTC") - btc_before)
        assert received.count("BTC") > btc_before
        assert "ETH" not in received and "DOGE" not in received

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
