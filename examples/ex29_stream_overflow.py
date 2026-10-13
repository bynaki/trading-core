"""ex29: `stream()`을 읽는 쪽이 밀릴 때 — 쌓인 것을 내준 뒤 `StageFailed`로 끝난다

`stream()`도 안에서는 `subscribe()`를 쓰므로 다른 소비자처럼 크기 제한 큐(`sender_buffer`)를 거친다.
`async for` 루프가 데이터 하나를 오래 붙잡고 있으면 그동안 큐가 쌓이고, 차면 코어는 데이터를 버리지
않고 구독을 끊는다. `stream()`은 실패하면 `StageFailed`를 던지고 끝나므로(ex20) 루프 밖에서 잡는다.
원인(`__cause__`)은 `SenderOverflow`다.

    소스 generator ─→ [큐: 5건] → [stream 안의 1건] → async for 루프 (한 건에 1초)
                       ↑ 차면 끊긴다

끊기기 전에 이미 `stream()` 안까지 넘어온 데이터는 버리지 않고 내준 뒤에 던진다. 큐에 남아 있던 것은
끊을 때 버려진다.

`sender_buffer`는 `Domain`을 만들 때 정한다. 이 예제는 상한을 5건으로 둔 `Domain`을 따로 띄운다.

배우는 것
- 제때 읽으면 `stream()`은 끊기지 않는다.
- 루프가 밀리면 `StageFailed`(원인 `SenderOverflow`)를 던지고 끝난다. 루프 밖에서 잡는다.

실행
    uv run examples/ex29_stream_overflow.py

기대 출력 (줄 앞의 레벨은 뺐다)
    ex29: ----- 1. 제때 읽는다 (sender_buffer=5) -----
    ex29: 읽은 건수 {n=10}
    ex29: ----- 2. 첫 데이터를 1.0초 동안 처리한다 -----
    ex29: 처리 {seq=0}
    ex29: 처리 {seq=1}
    ex29: 끊겼다 {symbols=['BTC/USD'], cause=SenderOverflow}
    ex29: 읽은 건수 {n=2}

2단계에서 첫 데이터(seq=0)를 처리하는 1초 동안 발행이 쌓여 끊겼다. 그때 이미 `stream()` 안에 넘어와
있던 seq=1은 내준 뒤에 `StageFailed`를 던졌다.

다음: ex30_mistakes.py — 등록·사용 실수
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    SenderOverflow,
    SourceRequest,
    StageFailed,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.05
WORK = 1.0
"""2단계에서 루프가 첫 데이터를 처리하는 시간."""
SENDER_BUFFER = 5
"""쌓아 둘 수 있는 데이터 건수. 기본값은 1000이다."""

log = get_logger("ex29")


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    seq: int


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    n = 0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, seq=n)
        n += 1
        await asyncio.sleep(INTERVAL)


# ===== 소비자 쪽 =====


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
    log.info("━━━━━━━━━━ 시작: stream()을 읽는 쪽이 밀릴 때 ━━━━━━━━━━")
    async with small_domain() as small:
        log.info(f"----- 1. 제때 읽는다 (sender_buffer={SENDER_BUFFER}) -----")
        n = 0
        async with small.stream(TickReq(), {"BTC/USD"}) as stream:
            async for _ in stream:
                n += 1
                if n == 10:
                    break
        log.info("읽은 건수", n=n)

        log.info(f"----- 2. 첫 데이터를 {WORK}초 동안 처리한다 -----")
        n = 0
        failure: StageFailed | None = None
        try:
            async with small.stream(TickReq(), {"BTC/USD"}) as stream:
                async for data in stream:
                    n += 1
                    log.info("처리", seq=cast_model(data, TickData).seq)
                    if n == 1:
                        await asyncio.sleep(WORK)  # 그동안 발행이 쌓인다
        except StageFailed as failed:
            failure = failed
            cause = type(failed.__cause__).__name__
            log.warning("끊겼다", symbols=sorted(failed.symbols), cause=cause)
        log.info("읽은 건수", n=n)
        assert failure is not None and isinstance(failure.__cause__, SenderOverflow)
        assert n == 2  # 끊기기 전에 넘어온 1건까지 읽었다
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
