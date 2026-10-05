"""ex21: init 콜백이 던질 때 — 스테이지를 세우지 않고 알린다

init 콜백은 스테이지가 설 때 한 번 불려 컨텍스트를 만든다. 거래소 로그인처럼 실패할 수 있는 일을
여기서 하기 쉽다. init이 던지면 코어는 이렇게 한다.

    스테이지를 세우지 않는다(generator도 `@detached`도 없다). 그 스테이지를 쓰려던 소비자에게
    자기 심볼만 담은 `StageFailed`를 `on_error`로 알린다. `update()`는 던지지 않는다.

파생 요청의 상위(소스 요청)에서 init이 던지면, 상위 스테이지가 실패한 것과 같이 파생 스테이지까지
내려간다(ex17의 연쇄와 같다). 파생 generator는 시작조차 하지 않는다.

    소비자 A ── TickReq(account="a")                       ← init이 던진다
    소비자 B ── PriceReq(account="b") ── TickReq(account="b")  ← init이 던진다

`account`가 다르면 content_id가 달라 스테이지가 따로 선다. 두 경우를 이것으로 나눴다.

배우는 것
- `update()`는 init 실패를 던지지 않는다. 실패는 `on_error`로 온다.
- 스테이지가 서지 않으므로 generator·`@detached`가 불리지 않고, 공유 목록도 비어 있다.
- 다시 넣으면 init부터 다시 한다. 코어가 알아서 다시 시도하지는 않는다.

실행
    uv run examples/ex21_init_failure.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex21: ----- 1. 소스 요청의 init이 던진다 -----
    ex21.tick: 로그인 {account=a, no=1}
    trading_core.domain: init 콜백이 실패했다
      ...
    PermissionError: API 키가 거부되었다
    ex21: 실패 통지 A {symbols=['BTC/USD', 'ETH/USD'], chained=False}
    ex21: 공유 목록 {source=[]}
    ex21: A가 다시 넣는다
    ex21.tick: 로그인 {account=a, no=2}
    ex21: ----- 2. 파생 요청의 상위 init이 던진다 -----
    ex21.tick: 로그인 {account=b, no=1}
    trading_core.domain: init 콜백이 실패했다
      ...
    trading_core.domain: 스테이지가 실패했다
      ... (상위의 PermissionError → StageFailed로 이어진 트레이스백)
    ex21: 실패 통지 B {symbols=['BTC'], chained=True}
    ex21: B가 다시 넣는다
    ex21.tick: 로그인 {account=b, no=2}
    ex21.price: generator 시작 {symbols=['BTC']}

`price: generator 시작`은 B가 다시 넣은 뒤에야 처음 나온다. 상위가 서지 못하면 파생 generator는
시작하지 않는다.

binder를 등록하지 않은 요청을 구독하는 것은 init 실패가 아니라 등록 실수다. 그때는 `on_error`가
아니라 `DomainError`가 호출자에게 던져진다(ex26).

다음: ex22_session_failure.py — 세션 요청의 실패
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

log = get_logger("ex21")
tick_log = get_logger("ex21.tick")
price_log = get_logger("ex21.price")

LOGINS: dict[str, int] = {}
"""계정별 로그인(init) 시도 수. 계정마다 첫 시도는 거부된다."""
EVENTS: list[str] = []


# ===== binder 쪽 (1): 소스 요청 — 계정마다 첫 로그인이 거부된다 =====


class TickReq(SourceRequest):
    account: str


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    LOGINS[req.account] = LOGINS.get(req.account, 0) + 1
    tick_log.info("로그인", account=req.account, no=LOGINS[req.account])
    if LOGINS[req.account] == 1:
        raise PermissionError("API 키가 거부되었다")
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    EVENTS.append(f"tick generator {ctx.account}")
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=100.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


@tick.detached
async def _(ctx: TickReq):
    EVENTS.append(f"tick detached {ctx.account}")


# ===== binder 쪽 (2): 파생 요청 =====


class PriceReq(DerivedRequest):
    account: str


class PriceData(DataModel):
    price: float


@PriceReq.require
def _(req: PriceReq, symbols: set[str]):
    return TickReq(account=req.account), {f"{s}/USD" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    """파생 자신의 init은 늘 성공한다. 실패는 상위의 init에서 난다."""

    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    price_log.info("generator 시작", symbols=sorted(symbols))
    EVENTS.append("price generator")
    while True:
        tick_data = cast_model(await recv(), TickData)
        yield PriceData(symbol=tick_data.symbol.removesuffix("/USD"), price=tick_data.price)


# ===== 소비자 쪽 =====


class Consumer:
    def __init__(self, name: str) -> None:
        self.name = name
        self.count = 0
        self.failures: list[StageFailed] = []

    async def __call__(self, data: DataModel) -> None:
        self.count += 1

    async def on_error(self, failed: StageFailed) -> None:
        self.failures.append(failed)
        chained = isinstance(failed.__cause__, StageFailed)
        log.warning(f"실패 통지 {self.name}", symbols=sorted(failed.symbols), chained=chained)

    async def wait(self, done) -> None:
        async with asyncio.timeout(3):
            while not done():
                await asyncio.sleep(0.05)


async def source_init(domain: Domain) -> None:
    log.info("----- 1. 소스 요청의 init이 던진다 -----")
    req = TickReq(account="a")
    a = Consumer("A")
    async with domain.subscribe(req, a, a.on_error) as sub:
        await sub.update({"BTC/USD", "ETH/USD"})  # 던지지 않는다
        await a.wait(lambda: a.failures)
        log.info("공유 목록", source=sorted(domain.get_shared_symbols(req.tr_content_id)))

        assert a.failures[0].symbols == {"BTC/USD", "ETH/USD"}  # 요청한 심볼 모두
        assert a.failures[0].cause == "PermissionError: API 키가 거부되었다"
        assert domain.get_shared_symbols(req.tr_content_id) == set()
        assert EVENTS == []  # 스테이지가 서지 않았다 — generator도 detached도 없다

        log.info("A가 다시 넣는다")
        await sub.update(set(a.failures[0].symbols))
        await a.wait(lambda: a.count > 0)
        assert LOGINS["a"] == 2


async def derived_upstream_init(domain: Domain) -> None:
    log.info("----- 2. 파생 요청의 상위 init이 던진다 -----")
    b = Consumer("B")
    async with domain.subscribe(PriceReq(account="b"), b, b.on_error) as sub:
        await sub.update({"BTC"})
        await b.wait(lambda: b.failures)

        upstream_failed = b.failures[0].__cause__
        assert b.failures[0].symbols == {"BTC"}  # 하위 표기로 받는다
        assert isinstance(upstream_failed, StageFailed)
        assert upstream_failed.symbols == {"BTC/USD"}  # 상위의 실패는 상위 표기
        assert "price generator" not in EVENTS  # 파생 generator는 시작하지 않았다

        log.info("B가 다시 넣는다")
        await sub.update({"BTC"})
        await b.wait(lambda: b.count > 0)
        assert LOGINS["b"] == 2


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: init 콜백이 던질 때 ━━━━━━━━━━")
    LOGINS.clear()
    EVENTS.clear()
    await source_init(domain)
    await derived_upstream_init(domain)
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
