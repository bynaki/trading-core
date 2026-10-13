"""ex18: 소비자 하나가 던질 때 — 그 소비자만 떼어 낸다

소비자의 Sender(데이터를 받는 콜백)가 던지는 경우다. 받은 데이터를 DB에 쓰다 실패하는 일 등이다.
같은 소스 스테이지를 여러 소비자가 나눠 쓰므로(ex04), 소비자 하나의 실수로 generator를 내리면
멀쩡한 다른 소비자까지 피해를 본다. 그래서 코어는 **던진 Sender만** 떼어 낸다.

    소비자 C {BTC/USD} ─┐
                        ├─ TickReq 소스 스테이지   generator는 계속 돈다
    소비자 D {BTC/USD} ─┘  ← D가 세 번째 데이터에서 던진다 → D만 떼고 D에게 알린다

떼어 낸 소비자에게는 `StageFailed`로 알린다. 원인(`cause`)은 D 자신의 예외다. 같은 심볼을 C가 아직
구독하므로 합집합은 그대로이고, generator는 재시작하지 않는다(ex06의 규칙).

배우는 것
- Sender가 던지면 그 Sender만 구독에서 빠지고, 자기 `on_error`로 `StageFailed`를 받는다.
- 같은 스테이지의 다른 소비자는 아무 일 없이 계속 받는다. 공유 generator는 실패를 모른다.
- 떼어진 소비자에게는 더 오지 않는다.

실행
    uv run examples/ex18_sender_failure.py

기대 출력 (줄 앞의 레벨은 뺐다)
    ex18.tick: generator 시작 {symbols=['BTC/USD']}
    ex18: 실패 통지 D {symbols=['BTC/USD'], cause=ValueError: D가 DB에 쓰지 못했다}
    ex18: ----- D가 떨어진 뒤 0.6초 -----
    ex18: 그동안 받은 건수 {c=3, d=0}

`generator 시작` 줄은 한 번뿐이다. D가 빠져도 재시작하지 않았다. 이번에는 코어의 ERROR 줄도 없다.
`on_error`를 준 소비자의 실패는 그 소비자가 다룰 일이라 코어는 알리기만 한다(원래 예외는
`failed.__cause__`에 있다). `on_error`가 없으면 코어가 ERROR 로그를 남긴다.

다음: ex19_cleanup_failure.py — 정리 콜백이 던질 때
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    SourceRequest,
    StageFailed,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2

log = get_logger("ex18")
tick_log = get_logger("ex18.tick")

GEN_STARTS: list[list[str]] = []


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    tick_log.info("generator 시작", symbols=sorted(symbols))
    GEN_STARTS.append(sorted(symbols))
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=100.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== 소비자 쪽 =====


class Consumer:
    """받은 건수를 세는 Sender이자 `on_error` 핸들러. `fail_at`번째 데이터에서 던진다."""

    def __init__(self, name: str, fail_at: int | None = None) -> None:
        self.name = name
        self.fail_at = fail_at
        self.count = 0
        self.failures: list[StageFailed] = []

    async def __call__(self, data: DataModel) -> None:
        self.count += 1
        if self.count == self.fail_at:
            raise ValueError(f"{self.name}가 DB에 쓰지 못했다")

    async def on_error(self, failed: StageFailed) -> None:
        self.failures.append(failed)
        log.warning(f"실패 통지 {self.name}", symbols=sorted(failed.symbols), cause=failed.cause)

    async def wait_failed(self) -> None:
        async with asyncio.timeout(3):
            while not self.failures:
                await asyncio.sleep(0.05)


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 소비자 하나가 던질 때 ━━━━━━━━━━")
    GEN_STARTS.clear()
    c = Consumer("C")
    d = Consumer("D", fail_at=3)

    async with (
        domain.subscribe(TickReq(), c, c.on_error) as sub_c,
        domain.subscribe(TickReq(), d, d.on_error) as sub_d,
    ):
        await sub_c.update({"BTC/USD"})
        await sub_d.update({"BTC/USD"})
        await d.wait_failed()

        log.info("----- D가 떨어진 뒤 0.6초 -----")
        c_before, d_before = c.count, d.count
        await asyncio.sleep(0.6)
        log.info("그동안 받은 건수", c=c.count - c_before, d=d.count - d_before)

        assert d.failures[0].symbols == {"BTC/USD"}
        assert d.failures[0].cause == "ValueError: D가 DB에 쓰지 못했다"
        assert not c.failures  # C는 실패를 모른다
        assert c.count > c_before  # C는 계속 받는다
        assert d.count == d_before  # 떼어진 D에는 더 오지 않는다
        assert GEN_STARTS == [["BTC/USD"]]  # generator는 한 번만 떴다

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
