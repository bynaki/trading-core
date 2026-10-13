"""ex04: 내용이 같은 요청은 스테이지 하나를 나눠 쓴다

여러 전략이 같은 거래소의 같은 시세를 원할 때, 소비자마다 연결을 따로 열면 낭비다. `Domain`은
요청의 **내용**이 같으면 스테이지(init 컨텍스트 + generator) 하나를 나눠 쓴다.

내용이 같은지는 `content_id`로 가린다. 요청 타입과 필드 값을 직렬화해 만든 digest다. 인스턴스가
달라도 필드 값이 같으면 같다.

배우는 것
- `TickReq(exchange="mock")`을 두 번 만들어도 `tr_content_id`가 같다 → init이 한 번만 불린다.
- 필드 값이 다르면(`exchange="other"`) content_id가 달라 스테이지도 따로 선다.
- 공유 중인 스테이지는 마지막 소비자가 떠날 때 내려간다.

실행
    uv run examples/ex04_sharing.py

기대 출력 (줄 앞의 레벨 `INFO  `는 뺐다)
    ex04: content_id 비교 {a_equals_b=True, a_equals_c=False}
    ex04.tick: init {exchange=mock}
    ex04.tick: init {exchange=other}
    ex04: 거래소별 init 횟수 {mock=1, other=1}
    ex04.tick: detached {exchange=other}
    ex04.tick: detached {exchange=mock}

다음: ex05_union.py — 소비자마다 심볼이 다르면?
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, SourceRequest, initialize
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
BASE_PRICE = {"BTC": 100.0}

log = get_logger("ex04")
tick_log = get_logger("ex04.tick")

INITS: dict[str, int] = {}
"""거래소별 init 횟수."""


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    exchange: str


class TickData(DataModel):
    price: float


@initialize
def tick(req: TickReq) -> TickReq:
    tick_log.info("init", exchange=req.exchange)
    INITS[req.exchange] = INITS.get(req.exchange, 0) + 1
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
    tick_log.info("detached", exchange=ctx.exchange)


# ===== 소비자 쪽 =====


class Counter:
    """받은 건수를 세는 Sender. `__call__`을 가진 객체도 Sender가 된다."""

    def __init__(self) -> None:
        self.count = 0

    async def __call__(self, data: DataModel) -> None:
        self.count += 1


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 내용이 같은 요청은 스테이지 하나를 나눠 쓴다 ━━━━━━━━━━")
    INITS.clear()
    req_a = TickReq(exchange="mock")
    req_b = TickReq(exchange="mock")  # A와 다른 인스턴스, 같은 내용
    req_c = TickReq(exchange="other")  # 내용이 다르다
    log.info(
        "content_id 비교",
        a_equals_b=req_a.tr_content_id == req_b.tr_content_id,
        a_equals_c=req_a.tr_content_id == req_c.tr_content_id,
    )
    a, b, c = Counter(), Counter(), Counter()

    async with (
        domain.subscribe(req_a, a) as sub_a,
        domain.subscribe(req_b, b) as sub_b,
        domain.subscribe(req_c, c) as sub_c,
    ):
        await sub_a.update({"BTC"})
        await sub_b.update({"BTC"})  # A가 세운 스테이지에 붙는다 — init 없음
        await sub_c.update({"BTC"})  # 따로 선다 — init 한 번 더
        await asyncio.sleep(0.5)
        log.info("거래소별 init 횟수", mock=INITS.get("mock"), other=INITS.get("other"))
        log.info("받은 건수", a=a.count, b=b.count, c=c.count)

    assert INITS == {"mock": 1, "other": 1}
    assert a.count > 0 and b.count > 0 and c.count > 0
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
