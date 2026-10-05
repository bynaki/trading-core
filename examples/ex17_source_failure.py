"""ex17: 소스 generator가 던질 때 — 재시도 없이 `StageFailed`로 알린다

ex16까지는 모든 콜백이 잘 돌았다. 여기부터는 콜백이 **예외를 던질 때** 코어가 무엇을 하는지 본다.
먼저 가장 흔한 일, 거래소 연결이 끊겨 소스 generator가 던지는 경우다.

코어의 정책은 이렇다.

    재시도하지 않는다. 실패한 스테이지를 내리고(`@detached`까지), 영향받은 소비자에게
    **자기 심볼만** 담은 `StageFailed`를 `on_error`로 알린다.

그 스테이지를 상위로 둔 파생 스테이지도 함께 내려간다(연쇄). 파생 소비자가 받는 `StageFailed`의
`__cause__`는 상위의 `StageFailed`다.

    소비자 A {ETH/USD} ─────────────────────┐
                                             ├─ TickReq 소스 스테이지  ← generator가 던진다
    소비자 B {BTC} ── PriceReq {BTC/USD} ───┘

    → A는 {ETH/USD}, B는 {BTC}만 실패로 받는다. B 쪽은 상위의 실패로 이어진다.

재시도는 binder 몫이다. 무해한 끊김을 버틸지(재연결 등)는 binder가 generator 안에서 `try`로 정한다.
코어까지 다시 시도하면 요청이 여러 단계를 거칠 때 재시도가 단계마다 곱해진다. 실패한 심볼은
구독에서 빠지고, 다시 받고 싶으면 소비자가 `update()`로 다시 넣는다. 그러면 새 스테이지가
init부터 선다.

배우는 것
- `subscribe(req, sender, on_error)`의 `on_error`가 `StageFailed`를 받는다. `symbols`는 그 소비자가
  잃은 심볼만, `cause`는 원인을 요약한 문자열이다.
- 코어는 다시 띄우지 않는다(init 1회). 실패한 심볼은 공유 목록에서 빠진다.
- 소비자가 `update()`로 다시 넣으면 init부터 다시 선다(init 2회).

실행
    uv run examples/ex17_source_failure.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex17: ----- 1. A는 {'ETH/USD'}, B는 {'BTC'} -----
    ex17.tick: init {no=1}
    ex17.tick: detached {no=1}
    trading_core.domain: 스테이지가 실패했다
      {"stage": "TickReq@...", "symbols": ["BTC/USD", "ETH/USD"]}
    Traceback (most recent call last):
      ...
    ConnectionError: 거래소 연결이 끊겼다
    ex17: 실패 통지 A {symbols=['ETH/USD'], chained=False}
    trading_core.domain: 스테이지가 실패했다
      {"stage": "PriceReq@...", "symbols": ["BTC"]}
      ... (상위의 ConnectionError → StageFailed로 이어진 트레이스백)
    ex17: 실패 통지 B {symbols=['BTC'], chained=True}
    ex17: ----- 2. 기다려 본다: 코어는 다시 띄우지 않는다 -----
    ex17: 공유 목록 {source=[]}
    ex17: ----- 3. A가 실패한 심볼을 update()로 다시 넣는다 -----
    ex17.tick: init {no=2}
    ex17: 다시 받은 건수 {a=3}
    ex17.tick: detached {no=2}

소스 스테이지의 합집합은 `{BTC/USD, ETH/USD}`인데 A는 `ETH/USD`만 받는다. `BTC/USD`는 B의 파생
스테이지가 상위에 등록한 심볼이라 A의 것이 아니다.

`trading_core.domain`의 ERROR 줄과 트레이스백은 고장이 아니라 이 예제가 일부러 낸 실패의 기록이다.
`on_error`를 주지 않으면 코어는 이 ERROR 로그만 남긴다.

다음: ex18_sender_failure.py — 소비자 하나가 던질 때
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    DerivedRequest,
    Domain,
    Receiver,
    SourceRequest,
    StageFailed,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
FAIL_AT = 3
"""첫 연결은 이 번째 바퀴에서 끊긴다."""

log = get_logger("ex17")
tick_log = get_logger("ex17.tick")

INITS: list[int] = []
DETACHES: list[int] = []


# ===== binder 쪽 (1): 소스 요청 — 첫 연결은 도중에 끊긴다 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    price: float


class Connection:
    """거래소 연결 흉내. `no`는 몇 번째 연결인지다."""

    def __init__(self, no: int) -> None:
        self.no = no


@initialize
def tick(req: TickReq) -> Connection:
    INITS.append(len(INITS) + 1)
    tick_log.info("init", no=INITS[-1])
    return Connection(INITS[-1])


@tick
async def _(ctx: Connection, symbols: set[str]):
    n = 0
    while True:
        if ctx.no == 1 and n == FAIL_AT:
            # 재연결하지 않고 그대로 던진다. 버틸 거라면 여기서 try로 감싼다.
            raise ConnectionError("거래소 연결이 끊겼다")
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=100.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


@tick.detached
async def _(ctx: Connection):
    """마지막 구독이 빠질 때뿐 아니라 스테이지가 실패할 때도 불린다."""

    tick_log.info("detached", no=ctx.no)
    DETACHES.append(ctx.no)


# ===== binder 쪽 (2): 파생 요청 — 위 소스 요청을 상위로 둔다 =====


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
    """상위가 실패해도 여기서 할 일은 없다. 코어가 이 스테이지까지 내린다."""

    while True:
        tick_data = cast_model(await recv(), TickData)
        yield PriceData(symbol=tick_data.symbol.removesuffix("/USD"), price=tick_data.price)


# ===== 소비자 쪽 =====


class Consumer:
    """받은 건수를 세는 Sender이자 `on_error` 핸들러."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.count = 0
        self.failures: list[StageFailed] = []

    async def __call__(self, data: DataModel) -> None:
        self.count += 1

    async def on_error(self, failed: StageFailed) -> None:
        """코어가 띄운 태스크에서 불린다. 여기서 던져도 코어가 ERROR 로그로 삼킨다."""

        self.failures.append(failed)
        chained = isinstance(failed.__cause__, StageFailed)
        log.warning(f"실패 통지 {self.name}", symbols=sorted(failed.symbols), chained=chained)

    async def wait_failed(self) -> None:
        async with asyncio.timeout(3):  # 회귀가 멈춤으로 나타나지 않게 한도를 둔다
            while not self.failures:
                await asyncio.sleep(0.05)


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 소스 generator가 던질 때 ━━━━━━━━━━")
    INITS.clear()
    DETACHES.clear()
    source_id = TickReq().tr_content_id
    a = Consumer("A")  # 소스 요청을 직접 구독
    b = Consumer("B")  # 같은 소스 스테이지를 상위로 둔 파생 요청을 구독

    async with (
        domain.subscribe(TickReq(), a, a.on_error) as sub_a,
        domain.subscribe(PriceReq(), b, b.on_error) as sub_b,
    ):
        log.info("----- 1. A는 {'ETH/USD'}, B는 {'BTC'} -----")
        await sub_a.update({"ETH/USD"})
        await sub_b.update({"BTC"})  # 소스 스테이지의 합집합은 {BTC/USD, ETH/USD}
        await a.wait_failed()
        await b.wait_failed()

        # 각자 자기 몫의 심볼만 받는다. B는 하위 표기(BTC)로 받는다.
        assert a.failures[0].symbols == {"ETH/USD"}
        assert b.failures[0].symbols == {"BTC"}
        assert a.failures[0].cause == "ConnectionError: 거래소 연결이 끊겼다"
        # B의 파생 스테이지는 스스로 던지지 않았다. 상위가 실패해 함께 내려갔다.
        assert isinstance(b.failures[0].__cause__, StageFailed)
        assert DETACHES == [1]

        log.info("----- 2. 기다려 본다: 코어는 다시 띄우지 않는다 -----")
        await asyncio.sleep(0.6)
        log.info("공유 목록", source=sorted(domain.get_shared_symbols(source_id)))
        assert INITS == [1]
        assert domain.get_shared_symbols(source_id) == set()

        log.info("----- 3. A가 실패한 심볼을 update()로 다시 넣는다 -----")
        before = a.count
        await sub_a.update(set(a.failures[0].symbols))
        await asyncio.sleep(0.5)
        log.info("다시 받은 건수", a=a.count - before)
        assert INITS == [1, 2]  # 새 스테이지가 init부터 섰다
        assert a.count > before

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
