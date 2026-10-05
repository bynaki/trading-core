"""ex03: 두 정리 지점 — generator의 `finally`와 `@detached`

binder는 자원을 두 단위로 쥔다.

- **스테이지 단위**: 거래소 연결처럼 요청이 살아 있는 동안 하나만 있으면 되는 것. init 콜백이 열고
  `@x.detached` 콜백이 닫는다. 마지막 구독이 빠질 때 **한 번** 불린다.
- **구독 단위**: "BTC·ETH를 구독한다"는 구독 메시지처럼 심볼 집합에 묶인 것. generate 콜백이
  시작하며 보내고 `finally`에서 거둔다. 심볼 집합이 바뀌면 `Domain`이 generator를 닫고 새 심볼로
  다시 띄우므로 그때마다 불린다.

배우는 것
- 심볼이 바뀌면 `finally` → generator 재시작. `@detached`는 불리지 않는다.
- 마지막 구독이 빠지면 `finally` → `@detached` 순서로 불린다.
- generator는 `update()` 뒤 태스크로 돈다. `update()`가 돌아온 순간엔 아직 시작 전일 수 있다.

실행
    uv run examples/ex03_cleanup.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex03: ----- update({'BTC'}) -----
    ex03.tick: init — 거래소 연결
    ex03.tick: generator 시작 — 구독 메시지 보냄 {symbols=['BTC']}
    ex03: ----- update({'BTC', 'ETH'}): 심볼이 바뀐다 -----
    ex03.tick: finally — 구독 메시지 거둠 {symbols=['BTC']}
    ex03.tick: generator 시작 — 구독 메시지 보냄 {symbols=['BTC', 'ETH']}
    ex03: ----- 블록을 벗어난다: 마지막 구독이 빠진다 -----
    ex03.tick: finally — 구독 메시지 거둠 {symbols=['BTC', 'ETH']}
    ex03.tick: detached — 거래소 연결 닫음

다음: ex04_sharing.py — 같은 요청을 여럿이 보내면 스테이지 하나를 나눠 쓴다
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, SourceRequest, initialize
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
BASE_PRICE = {"BTC": 100.0, "ETH": 200.0}

log = get_logger("ex03")
tick_log = get_logger("ex03.tick")

EVENTS: list[str] = []
"""binder 콜백이 불린 차례. `run_ex()`가 순서를 확인한다."""


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    exchange: str


class TickData(DataModel):
    price: float


class Connection:
    """거래소 연결 흉내. 스테이지 단위 자원이다."""

    def __init__(self, exchange: str) -> None:
        self.exchange = exchange
        self.open = True


@initialize
def tick(req: TickReq) -> Connection:
    """스테이지가 설 때 한 번. 연결을 열어 컨텍스트로 돌려준다."""

    tick_log.info("init — 거래소 연결")
    EVENTS.append("init")
    return Connection(req.exchange)


@tick
async def _(conn: Connection, symbols: set[str]):
    """심볼 집합 하나에 대한 구독. 시작에서 보내고 `finally`에서 거둔다."""

    tick_log.info("generator 시작 — 구독 메시지 보냄", symbols=sorted(symbols))
    EVENTS.append(f"start {sorted(symbols)}")
    try:
        n = 0
        while True:
            for symbol in sorted(symbols):
                yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + n)
            n += 1
            await asyncio.sleep(INTERVAL)
    finally:
        # 재시작이든 마지막 정리든 generator가 닫힐 때 여기를 지난다.
        tick_log.info("finally — 구독 메시지 거둠", symbols=sorted(symbols))
        EVENTS.append("finally")


@tick.detached
async def _(conn: Connection):
    """마지막 구독이 빠져 스테이지가 내려갈 때 한 번. 연결을 닫는다."""

    conn.open = False
    tick_log.info("detached — 거래소 연결 닫음")
    EVENTS.append("detached")


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 두 정리 지점 — generator의 finally와 @detached ━━━━━━━━━━")
    EVENTS.clear()

    async def ignore(data: DataModel) -> None:
        """이 예제는 받은 데이터를 보지 않는다."""

    async with domain.subscribe(TickReq(exchange="mock"), ignore) as sub:
        log.info("----- update({'BTC'}) -----")
        await sub.update({"BTC"})
        # generator는 태스크로 시작한다. 시작하기 전에 심볼을 바꾸면 시작 없이 취소되므로
        # (finally도 없이) 잠깐 기다린다.
        await asyncio.sleep(0.3)

        log.info("----- update({'BTC', 'ETH'}): 심볼이 바뀐다 -----")
        await sub.update({"BTC", "ETH"})
        await asyncio.sleep(0.3)

        log.info("----- 블록을 벗어난다: 마지막 구독이 빠진다 -----")

    assert EVENTS == [
        "init",
        "start ['BTC']",
        "finally",  # 심볼이 바뀌어 재시작 — detached는 없다
        "start ['BTC', 'ETH']",
        "finally",  # 마지막 구독이 빠짐 — 구독 단위 정리가 먼저
        "detached",  # 그다음 스테이지 단위 정리
    ], EVENTS
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
