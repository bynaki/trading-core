"""ex13: 내용이 같아도 세션 요청은 나눠 쓰지 않는다

소스·파생 요청은 content_id가 같으면 스테이지 하나를 나눠 쓴다(ex04). 세션 요청은 **그렇지 않다.**
세션은 소비자마다 상태를 들고 계산하는 용도라서(전략이 보는 차트, 체결 기록 등), 남의 상태와 섞이면
안 된다. 그래서 같은 요청을 둘이 구독하면 init·bind가 소비자마다 따로 불리고 컨텍스트도 따로다.

공유는 그 아래 단계에서 일어난다. 두 세션이 파이프라인으로 붙는 소스 스테이지는 content_id 기준으로
여전히 하나다.

    소비자 A ── CountReq() ─ 컨텍스트 A ─┐
                                          ├─→ TickReq()   ← 소스 스테이지는 하나
    소비자 B ── CountReq() ─ 컨텍스트 B ─┘

배우는 것
- 같은 `CountReq()`를 둘이 구독해도 세션 init은 두 번, 소스 init은 한 번이다.
- 컨텍스트가 따로라 카운터도 따로 센다. 둘 다 1부터 센다.
- 세션 스테이지는 공유 목록에 오르지 않는다. `get_shared_symbols()`는 세션 요청에 대해 빈 집합이다.

실행
    uv run examples/ex13_not_shared.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex13: content_id가 같은가 {same=True}
    ex13.count: init {no=1}
    ex13.tick: init
    ex13.count: init {no=2}
    ex13: 공유 목록 {session=[], source=['BTC/USD']}
    ex13: 받은 번호 {a=[1, 2, 3], b=[1, 2, 3]}

다음: ex14_multi_step.py — 단계가 여럿인 파이프라인
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    Runnable,
    SessionRequest,
    SourceRequest,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2

log = get_logger("ex13")
tick_log = get_logger("ex13.tick")
count_log = get_logger("ex13.count")

TICK_INITS: list[str] = []
SESSION_INITS: list[int] = []


# ===== binder 쪽 (1): 소스 요청 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    tick_log.info("init")
    TICK_INITS.append("tick")
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=100.0 + n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== binder 쪽 (2): 세션 요청 — 받은 순번을 컨텍스트에 센다 =====


class CountReq(SessionRequest):
    pass


class CountData(DataModel):
    no: int
    """이 컨텍스트가 내보낸 순번(1부터)."""


class CountCtx:
    def __init__(self, ctx_no: int) -> None:
        self.ctx_no = ctx_no
        self.count = 0


class Numbering(Runnable[TickData, CountData]):
    def __init__(self, ctx: CountCtx, symbol: str) -> None:
        self.ctx = ctx
        self.symbol = symbol

    async def invoke(self, input: TickData) -> CountData:
        self.ctx.count += 1
        return CountData(symbol=self.symbol, no=self.ctx.count)


@initialize
def count(req: CountReq) -> CountCtx:
    """구독마다 불린다. content_id가 같아도 마찬가지다."""

    SESSION_INITS.append(len(SESSION_INITS) + 1)
    count_log.info("init", no=SESSION_INITS[-1])
    return CountCtx(SESSION_INITS[-1])


@count
async def _(ctx: CountCtx, symbol: str):
    yield TickReq()(f"{symbol}/USD") | Numbering(ctx, symbol)


# ===== 소비자 쪽 =====


class Recorder:
    def __init__(self) -> None:
        self.numbers: list[int] = []

    async def __call__(self, data: DataModel) -> None:
        self.numbers.append(cast_model(data, CountData).no)


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 내용이 같아도 세션 요청은 나눠 쓰지 않는다 ━━━━━━━━━━")
    TICK_INITS.clear()
    SESSION_INITS.clear()
    req_a, req_b = CountReq(), CountReq()
    log.info("content_id가 같은가", same=req_a.tr_content_id == req_b.tr_content_id)
    a, b = Recorder(), Recorder()

    async with domain.subscribe(req_a, a) as sub_a, domain.subscribe(req_b, b) as sub_b:
        await sub_a.update({"BTC"})
        await sub_b.update({"BTC"})
        session = domain.get_shared_symbols(req_a.tr_content_id)
        source = domain.get_shared_symbols(TickReq().tr_content_id)
        log.info("공유 목록", session=sorted(session), source=sorted(source))
        await asyncio.sleep(0.7)
    log.info("받은 번호", a=a.numbers[:3], b=b.numbers[:3])

    assert len(SESSION_INITS) == 2  # 세션 컨텍스트는 소비자마다
    assert TICK_INITS == ["tick"]  # 소스 스테이지는 하나
    assert session == set()  # 세션은 공유 목록에 없다
    assert source == {"BTC/USD"}
    # 하나의 카운터를 나눠 썼다면 한쪽은 [1, 3, 5, ...]처럼 건너뛰었을 것이다.
    assert a.numbers[:3] == [1, 2, 3] and b.numbers[:3] == [1, 2, 3]
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
