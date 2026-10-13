"""ex20: `stream()`으로 받을 때의 실패 — `StageFailed`가 던져진다

`subscribe()`는 실패를 `on_error`로 알린다(ex17). 간편 API인 `stream()`에는 `on_error`를 줄 곳이
없다. 대신 실패하면 `async for`에서 `StageFailed`를 **던지고** 끝난다. 그러니 `try`로 감싸 받는다.

    try:
        async with domain.stream(req, symbols) as stream:
            async for data in stream:
                ...
    except StageFailed as failed:
        ...  # failed.symbols, failed.cause

`stream()`은 테스트·스크립트처럼 짧게 쓰는 용도다. 실패한 심볼만 다시 넣는 식의 세밀한 대응이
필요하면 `subscribe()`와 `on_error`를 쓴다.

배우는 것
- `stream()`은 실패하면 `StageFailed`를 던진다. 받은 데이터는 그 전까지 정상으로 온다.
- 실패한 스테이지는 던지기 전에 이미 내려갔다(`@detached`). `async with`를 빠져나오며 구독도 닫힌다.
- 실패를 기다리는 코드는 제한 시간을 두는 편이 좋다. 실패가 안 오면 멈춤으로 나타나기 때문이다.

실행
    uv run examples/ex20_stream_failure.py

기대 출력 (줄 앞의 레벨은 뺐고, 트레이스백은 줄였다)
    ex20: 수신 {seq=0}
    ex20: 수신 {seq=1}
    ex20: 수신 {seq=2}
    ex20.tick: detached
    trading_core.domain: 스테이지가 실패했다
      {"stage": "TickReq@...", "symbols": ["BTC/USD"]}
    Traceback (most recent call last):
      ...
    ConnectionError: 거래소 연결이 끊겼다
    ex20: StageFailed를 받았다 {symbols=['BTC/USD'], cause=ConnectionError: 거래소 연결이 끊겼다}

다음: ex21_init_failure.py — init 콜백이 던질 때
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    SourceRequest,
    StageFailed,
    cast_model,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2
FAIL_AT = 3

log = get_logger("ex20")
tick_log = get_logger("ex20.tick")


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
        if n == FAIL_AT:
            raise ConnectionError("거래소 연결이 끊겼다")
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, seq=n)
        n += 1
        await asyncio.sleep(INTERVAL)


@tick.detached
async def _(ctx: TickReq):
    tick_log.info("detached")


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: stream()으로 받을 때의 실패 ━━━━━━━━━━")
    seqs: list[int] = []
    caught: StageFailed | None = None

    try:
        async with asyncio.timeout(3):  # 실패가 오지 않으면 멈추는 대신 TimeoutError
            async with domain.stream(TickReq(), {"BTC/USD"}) as stream:
                async for data in stream:
                    item = cast_model(data, TickData)
                    log.info("수신", seq=item.seq)
                    seqs.append(item.seq)
    except StageFailed as failed:
        caught = failed
        log.warning("StageFailed를 받았다", symbols=sorted(failed.symbols), cause=failed.cause)

    assert seqs == [0, 1, 2]  # 실패 전까지는 정상으로 왔다
    assert caught is not None
    assert caught.symbols == {"BTC/USD"}
    assert caught.cause == "ConnectionError: 거래소 연결이 끊겼다"
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
