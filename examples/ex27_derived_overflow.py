"""ex27: 파생 generator가 상위를 따라가지 못할 때 — 그 파생 스테이지 전체가 끊긴다

파생 스테이지는 상위 데이터를 큐에 받아 두고 generator가 `recv()`로 꺼낸다(ex07). 상위 소스
generator는 그 큐에 넣기만 하고 기다리지 않는다. 파생 generator가 무거운 계산 때문에 상위보다 느리면
큐가 쌓이고, `sender_buffer`건이 차면 코어는 데이터를 버리지 않고 **그 파생 스테이지를 내린다.**

    소스 generator ─→ [C의 큐] → C  (소스 요청을 직접 구독. 제때 받는다)
                  └─→ [파생 스테이지의 큐] → 파생 generator (한 건에 0.2초)
                       ↑ 5건이 차면 파생 스테이지가 실패한다 → A·B 모두에게 알린다

파생 generator는 스테이지에 하나뿐이고 소비자 모두가 나눠 쓴다. 그래서 끊기는 단위는 소비자 하나가
아니라 **그 파생 스테이지 전체**다. A는 `{BTC}`, B는 `{ETH}`만 구독했지만 둘 다 실패를 받는다.
실패는 파생 스테이지 자신의 것으로 알린다(`content_id`가 파생 요청의 것). 상위 소스 스테이지는
실패하지 않으며, 소스 요청을 직접 구독한 C는 계속 받는다.

`sender_buffer`는 `Domain`을 만들 때 정한다. 이 예제는 상한을 5건으로 둔 `Domain`을 따로 띄운다.

배우는 것
- 파생 generator가 밀리면 상위를 붙잡지 않고 그 파생 스테이지가 실패한다.
- 파생 스테이지를 나눠 쓰는 소비자 모두가 자기 심볼(하위 표기)로 실패를 받는다.
- 상위 소스 스테이지와 그 다른 소비자는 그대로 돈다.

실행
    uv run examples/ex27_derived_overflow.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex27: ----- 1. 파생 generator가 한 건에 0.2초씩 걸린다 (sender_buffer=5) -----
    ex27.price: detached
    trading_core.domain: 스테이지가 실패했다 {"stage": "PriceReq@...", "symbols": ["BTC", "ETH"]}
      ... SenderOverflow: 처리하지 못한 상위 데이터가 5건 쌓였다.
    ex27: 끊겼다 A {symbols=['BTC'], cause=SenderOverflow, failed=price}
    ex27: 끊겼다 B {symbols=['ETH'], cause=SenderOverflow, failed=price}
    ex27: 받은 건수 {a=0, b=0, c=40}
    (C의 건수는 실행마다 조금씩 다르다)

파생 generator가 첫 계산(0.2초)을 끝내기도 전에 상위 데이터 5건이 쌓여 스테이지가 내려갔다. 그래서
A·B는 하나도 받지 못했다. `detached`와 ERROR 줄은 코어가 파생 스테이지를 내리며 남긴 것이다. 그동안
C는 BTC/USD·ETH/USD를 1초에 40건쯤 제때 받았다.

다음: ex28_session_overflow.py — 세션의 슬롯이 밀릴 때
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from trading_core import (
    DataModel,
    DerivedRequest,
    Domain,
    Receiver,
    SenderOverflow,
    SourceRequest,
    StageFailed,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.05
WORK = 0.2
"""파생 generator가 데이터 하나를 계산하는 시간."""
SENDER_BUFFER = 5
"""처리하지 못한 데이터를 쌓아 둘 수 있는 건수. 기본값은 1000이다."""
WINDOW = 1.0
"""받는 시간."""

log = get_logger("ex27")
price_log = get_logger("ex27.price")


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


# ===== binder 쪽 (2): 파생 요청 — 무거운 계산 =====


class PriceReq(DerivedRequest):
    """소비자 표기(`"BTC"`)로 계산한 가격을 받는 요청."""


class PriceData(DataModel):
    price: float


@PriceReq.require
def _(req: PriceReq, symbols: set[str]) -> tuple[TickReq, set[str]]:
    return TickReq(), {f"{s}/USD" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    while True:
        tick = cast_model(await recv(), TickData)
        await asyncio.sleep(WORK)  # 상위보다 느린 계산
        yield PriceData(symbol=tick.symbol.removesuffix("/USD"), price=tick.price)


@price.detached
async def _(ctx: PriceReq):
    price_log.info("detached")


# ===== 소비자 쪽 =====


class Consumer:
    """받은 건수와 실패를 남기는 소비자."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.count = 0
        self.failures: list[StageFailed] = []

    async def __call__(self, data: DataModel) -> None:
        self.count += 1

    async def on_error(self, failed: StageFailed) -> None:
        self.failures.append(failed)


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
    log.info("━━━━━━━━━━ 시작: 파생 generator가 상위를 따라가지 못할 때 ━━━━━━━━━━")
    a, b, c = Consumer("A"), Consumer("B"), Consumer("C")
    async with small_domain() as small:
        async with (
            small.subscribe(TickReq(), c, c.on_error) as sub_c,
            small.subscribe(PriceReq(), a, a.on_error) as sub_a,
            small.subscribe(PriceReq(), b, b.on_error) as sub_b,
        ):
            log.info(
                f"----- 1. 파생 generator가 한 건에 {WORK}초씩 걸린다 "
                f"(sender_buffer={SENDER_BUFFER}) -----"
            )
            await sub_c.update({"BTC/USD", "ETH/USD"})
            await sub_a.update({"BTC"})
            await sub_b.update({"ETH"})
            await asyncio.sleep(WINDOW)

            names = {PriceReq().tr_content_id: "price", TickReq().tr_content_id: "tick"}
            for consumer in (a, b):
                for failed in consumer.failures:
                    log.warning(
                        f"끊겼다 {consumer.name}",
                        symbols=sorted(failed.symbols),
                        cause=type(failed.__cause__).__name__,
                        failed=names[failed.content_id],
                    )
            log.info("받은 건수", a=a.count, b=b.count, c=c.count)

            for consumer, symbols in ((a, {"BTC"}), (b, {"ETH"})):
                [failed] = consumer.failures
                assert failed.content_id == PriceReq().tr_content_id  # 상위가 아니라 파생의 실패
                assert failed.symbols == symbols
                assert isinstance(failed.__cause__, SenderOverflow)
            assert c.failures == [] and c.count >= 10  # 상위는 붙잡히지 않았다
            assert small.get_shared_symbols(PriceReq().tr_content_id) == set()
            assert small.get_shared_symbols(TickReq().tr_content_id) == {"BTC/USD", "ETH/USD"}
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
