"""ex10: 파생 요청 위에 파생 요청 — 여러 단계로 잇기

파생 요청의 `require`는 소스 요청만이 아니라 **다른 파생 요청**도 돌려줄 수 있다. 그러면 단계가
여럿인 사슬이 된다.

    소비자 A ── AvgReq(window=3) ─→ KrwReq ─→ TickReq     (이동평균 ← 원화 환산 ← 체결가)
    소비자 B ───────────────────────┘                     (B는 원화 환산만 받는다)

소비자는 맨 위 요청 하나만 안다. `Domain`이 `require`를 따라 내려가며 단계마다 스테이지를 세우고
이어 준다. 단계마다 content_id로 공유하므로, B가 사슬 중간의 `KrwReq`를 직접 구독하면 A의 사슬이
쓰는 `KrwReq` 스테이지를 나눠 쓴다.

배우는 것
- `require`가 파생 요청을 돌려주면 사슬이 된다. 깊이에 제한은 없다(순환만 안 된다).
- 사슬의 중간 단계도 content_id가 같으면 다른 소비자와 공유한다(init 한 번).
- 마지막 소비자가 떠나면 사슬의 모든 스테이지가 내려간다.

실행
    uv run examples/ex10_chained.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex10.avg: init {window=3}
    ex10.krw: init
    ex10.tick: init
    ex10: 단계별 심볼 {avg=['BTC'], krw=['BTC'], tick=['BTC']}
    ex10: A가 받은 이동평균 {first_three=[140000.0, 140700.0, 141400.0]}
    ex10: B가 받은 원화 가격 {first_three=[140000.0, 141400.0, 142800.0]}
    ex10.tick: detached
    ex10.krw: detached
    ex10.avg: detached

사슬이 내려갈 때 `@detached`는 **아래(소스 스테이지)부터** 불린다. 맨 위 스테이지가 내려가며 상위
구독을 빼고, 그 상위가 다시 자기 상위를 빼는 식으로 끝까지 내려간 뒤에 각자의 정리가 돌아오기
때문이다. 그러니 하위의 detach 콜백에서 상위 스테이지가 아직 살아 있다고 기대하면 안 된다.

다음: ex11_session.py — 심볼마다 따로 도는 세션 요청
"""

import asyncio
from collections import Counter, deque
from pathlib import Path

from trading_core import (
    DataModel,
    DerivedRequest,
    Domain,
    Receiver,
    SourceRequest,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
BASE_PRICE = {"BTC": 100.0}
KRW_PER_USD = 1400.0

log = get_logger("ex10")
tick_log = get_logger("ex10.tick")
krw_log = get_logger("ex10.krw")
avg_log = get_logger("ex10.avg")

INITS: Counter[str] = Counter()
"""단계별 init 횟수."""


# ===== binder 쪽 (1): 소스 요청 — 체결가(USD) =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    tick_log.info("init")
    INITS["tick"] += 1
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=BASE_PRICE[symbol] + n)
        n += 1
        await asyncio.sleep(INTERVAL)


@tick.detached
async def _(ctx: TickReq):
    tick_log.info("detached")


# ===== binder 쪽 (2): 1단 파생 — 원화 환산 =====


class KrwReq(DerivedRequest):
    pass


class KrwData(DataModel):
    price: float


@KrwReq.require
def _(req: KrwReq) -> TickReq:
    return TickReq()


@initialize
def krw(req: KrwReq) -> KrwReq:
    krw_log.info("init")
    INITS["krw"] += 1
    return req


@krw
async def _(ctx: KrwReq, symbols: set[str], recv: Receiver):
    while True:
        tick = cast_model(await recv(), TickData)
        yield KrwData(symbol=tick.symbol, price=tick.price * KRW_PER_USD)


@krw.detached
async def _(ctx: KrwReq):
    krw_log.info("detached")


# ===== binder 쪽 (3): 2단 파생 — 원화 가격의 이동평균 =====


class AvgReq(DerivedRequest):
    window: int


class AvgData(DataModel):
    price: float


@AvgReq.require
def _(req: AvgReq) -> KrwReq:
    """상위로 **파생 요청**을 돌려준다. 이것으로 사슬이 한 단 더 길어진다."""

    return KrwReq()


@initialize
def avg(req: AvgReq) -> AvgReq:
    avg_log.info("init", window=req.window)
    INITS["avg"] += 1
    return req


@avg
async def _(ctx: AvgReq, symbols: set[str], recv: Receiver):
    """심볼마다 최근 `window`개의 평균을 낸다. 바로 위 단계(`KrwData`)만 알면 된다."""

    recent: dict[str, deque[float]] = {}
    while True:
        krw_price = cast_model(await recv(), KrwData)
        prices = recent.setdefault(krw_price.symbol, deque(maxlen=ctx.window))
        prices.append(krw_price.price)
        yield AvgData(symbol=krw_price.symbol, price=sum(prices) / len(prices))


@avg.detached
async def _(ctx: AvgReq):
    avg_log.info("detached")


# ===== 소비자 쪽 =====


class Recorder:
    """받은 가격을 모으는 Sender. 어떤 타입으로 좁힐지 만들 때 정한다."""

    def __init__(self, model: type[AvgData | KrwData]) -> None:
        self.model = model
        self.prices: list[float] = []

    async def __call__(self, data: DataModel) -> None:
        self.prices.append(cast_model(data, self.model).price)


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 파생 요청 위에 파생 요청 ━━━━━━━━━━")
    INITS.clear()
    a, b = Recorder(AvgData), Recorder(KrwData)

    async with (
        domain.subscribe(AvgReq(window=3), a) as sub_a,
        domain.subscribe(KrwReq(), b) as sub_b,
    ):
        await sub_a.update({"BTC"})  # 사슬 세 단계가 모두 선다
        await sub_b.update({"BTC"})  # 이미 선 KrwReq 스테이지에 붙는다 — init 없음
        log.info(
            "단계별 심볼",
            avg=sorted(domain.get_shared_symbols(AvgReq(window=3).tr_content_id)),
            krw=sorted(domain.get_shared_symbols(KrwReq().tr_content_id)),
            tick=sorted(domain.get_shared_symbols(TickReq().tr_content_id)),
        )
        await asyncio.sleep(0.7)
        log.info("A가 받은 이동평균", first_three=a.prices[:3])
        log.info("B가 받은 원화 가격", first_three=b.prices[:3])

    assert INITS == {"avg": 1, "krw": 1, "tick": 1}  # KrwReq는 A의 사슬과 B가 나눠 쓴다
    assert b.prices[:3] == [140000.0, 141400.0, 142800.0]
    # 140000 → (140000+141400)/2 → (140000+141400+142800)/3
    assert a.prices[:3] == [140000.0, 140700.0, 141400.0]
    # 블록을 벗어나면 사슬 전체가 내려간다.
    assert domain.get_shared_symbols(TickReq().tr_content_id) == set()
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
