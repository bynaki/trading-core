"""ex26: 등록·사용 실수 — `BindError`·`DomainError`·`ModelError`

ex17~24의 실패는 실행 중에 일어나는 일(연결 끊김 등)이라 `on_error`로 알렸다. 이 예제의 것은
다르다. **코드를 잘못 쓴 것**이라 고칠 때까지 매번 똑같이 실패하므로, 코어는 알림으로 돌리지 않고
그 자리에서 던진다.

| 실수 | 예외 | 어디서 |
| --- | --- | --- |
| 같은 요청에 `@initialize`를 두 번 | `BindError` | 데코레이터가 실행될 때(import 때) |
| init 콜백의 첫 인자에 요청 타입 어노테이션이 없다 | `BindError` | 〃 |
| binder를 등록하지 않은 요청을 구독 | `DomainError` | `subscribe()` |
| 파생 요청에 `require`가 없다 | `ModelError` | 첫 `update()` |
| 끊긴 구독의 `update()` | `DomainError` | 그 `update()` |

binder 등록은 import 때 모듈 수준에서 하므로, 앞의 둘은 대개 프로그램이 뜨자마자 드러난다. 이
예제는 보이려고 `run_ex()` 안에서 일부러 데코레이터를 다시 부른다.

init만 등록하고 generator(`@x`)를 붙이지 않은 요청도 등록되지 않은 것으로 본다. 요청의 종류는
generator를 등록할 때 정해진다.

배우는 것
- 등록 실수는 `BindError`로, 데코레이터가 실행될 때 바로 던져진다.
- 등록되지 않은 요청이나 끊긴 구독을 쓰면 `DomainError`가 호출자에게 던져진다(`on_error`가 아니다).

실행
    uv run examples/ex26_mistakes.py

기대 출력 (줄 앞의 레벨은 뺐다. 메시지는 ` - ` 뒤의 모델 이름을 잘라 보인다)
    ex26: ----- 1. 같은 요청에 @initialize를 두 번 -----
    ex26: BindError {error=이미 'binder'가 있다.}
    ex26: ----- 2. init 콜백의 첫 인자에 어노테이션이 없다 -----
    ex26: BindError {error='init' 콜백의 첫 인자 'req'에 요청 타입 어노테이션이 있어야 한다.}
    ex26: ----- 3. 등록하지 않은 요청을 구독한다 -----
    ex26: DomainError {error=지원 되는 요청이 아니거나 등록된 요청이 아니다.}
    ex26: DomainError {error=지원 되는 요청이 아니거나 등록된 요청이 아니다.}
    ex26: ----- 4. require가 없는 파생 요청 -----
    ex26: ModelError {error='require' 정의가 필요하다.}
    ex26: ----- 5. 끊긴 구독을 다시 쓴다 -----
    ex26: DomainError {error=이미 `detach`되었다.}

다음: ex27_identifiers.py — 식별자 셋과 가변 모델
"""

import asyncio
from pathlib import Path

from trading_core import (
    BindError,
    DataModel,
    DerivedRequest,
    Domain,
    DomainError,
    ModelError,
    Receiver,
    SourceRequest,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2

log = get_logger("ex26")


# ===== binder 쪽: 제대로 등록한 소스 요청 하나와, 잘못 쓴 요청들 =====


class TickReq(SourceRequest):
    pass


@initialize
def tick(req: TickReq) -> TickReq:
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    while True:
        for symbol in sorted(symbols):
            yield DataModel(symbol=symbol)
        await asyncio.sleep(INTERVAL)


class UnboundReq(SourceRequest):
    """binder를 등록하지 않았다."""


class InitOnlyReq(SourceRequest):
    """init만 등록하고 generator를 붙이지 않았다."""


@initialize
def init_only(req: InitOnlyReq) -> InitOnlyReq:
    return req


class NoRequireReq(DerivedRequest):
    """`@NoRequireReq.require`를 잊었다."""


@initialize
def no_require(req: NoRequireReq) -> NoRequireReq:
    return req


@no_require
async def _(ctx: NoRequireReq, symbols: set[str], recv: Receiver):
    while True:
        yield await recv()


# ===== 소비자 쪽 =====


async def ignore(data: DataModel) -> None:
    pass


def caught(exc: Exception) -> None:
    log.warning(type(exc).__name__, error=str(exc).split(" - ")[0])


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 등록·사용 실수 ━━━━━━━━━━")
    errors: list[type[Exception]] = []

    log.info("----- 1. 같은 요청에 @initialize를 두 번 -----")
    try:

        @initialize
        def tick_again(req: TickReq) -> TickReq:
            return req

    except BindError as exc:
        caught(exc)
        errors.append(type(exc))

    log.info("----- 2. init 콜백의 첫 인자에 어노테이션이 없다 -----")
    try:

        @initialize
        def no_hint(req) -> None:  # 일부러 뺐다
            return None

    except BindError as exc:
        caught(exc)
        errors.append(type(exc))

    log.info("----- 3. 등록하지 않은 요청을 구독한다 -----")
    for req in (UnboundReq(), InitOnlyReq()):
        try:
            async with domain.subscribe(req, ignore) as sub:
                await sub.update({"BTC/USD"})
        except DomainError as exc:
            caught(exc)
            errors.append(type(exc))

    log.info("----- 4. require가 없는 파생 요청 -----")
    try:
        async with domain.subscribe(NoRequireReq(), ignore) as sub:
            await sub.update({"BTC"})  # subscribe()는 지나가고 여기서 던진다
    except ModelError as exc:
        caught(exc)
        errors.append(type(exc))

    log.info("----- 5. 끊긴 구독을 다시 쓴다 -----")
    async with domain.subscribe(TickReq(), ignore) as sub:
        await sub.update({"BTC/USD"})
    try:
        await sub.update({"BTC/USD"})  # async with를 벗어나 이미 끊겼다
    except DomainError as exc:
        caught(exc)
        errors.append(type(exc))

    assert errors == [BindError, BindError, DomainError, DomainError, ModelError, DomainError]
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
