"""ex27: 식별자 셋과 가변 모델 — uid · model_id · content_id

요청·데이터 모델에는 식별자가 셋 있다. 이름이 비슷하지만 하는 일이 다르다.

| 식별자 | 같으면 | 쓰임 |
| --- | --- | --- |
| uid (`get_model_uid`) | 같은 객체 | 모델 하나하나를 추적 |
| model_id (`get_model_id`) | 같은 클래스 | binder 레지스트리 키, `cast_model()`의 기준 |
| content_id (`.tr_content_id`) | 같은 클래스·같은 내용 | **스테이지 공유의 기준**(ex04) |

꼴은 uid가 `클래스@모듈:인스턴스ID:순번`, model_id가 `클래스@모듈:필드이름digest`, content_id가
`모듈@클래스:내용digest`다. 인스턴스 ID에 `@`·`:`가 들어 있으니 uid를 구분자로 쪼개지 않는다.

내용이 같은 요청 둘은 uid만 다르고 model_id·content_id는 같다. 그래서 스테이지 하나를 나눠 쓴다.

모델은 **가변**이다. 필드를 고치면 content_id도 바뀐다(캐시를 그때 비운다). 바뀔 수 있으므로
hashable이 아니어서 `set`·dict 키로 쓸 수 없다. 키가 필요하면 content_id를 쓴다.

구독한 뒤 요청을 고치면? `Domain`은 구독하는 순간 요청의 **사본**을 찍어 두므로, 구독은 처음 내용에
묶여 있다. 고친 요청은 구독과 상관없다.

`compute_tr_content_id(include=..., exclude=...)`는 고른 필드로만 content_id를 계산한다. 예를 들어
표시용 필드를 빼고 "사실상 같은 요청"인지 볼 때 쓴다. `Domain`의 공유 기준은 언제나 모든 필드다.

배우는 것
- 같은 내용의 요청 둘: uid는 다르고 model_id·content_id는 같다.
- 필드를 고치면 content_id가 바뀐다. 모델은 `set`에 넣을 수 없다.
- 구독은 요청의 사본에 묶인다. 구독한 뒤 고쳐도 구독은 처음 스테이지에 남는다.

실행
    uv run examples/ex27_identifiers.py

기대 출력 (줄 앞의 레벨은 뺐다. 식별자는 끝 조각만 보인다)
    ex27: ----- 1. 내용이 같은 요청 둘 -----
    ex27: uid 끝 순번 {a=1, b=2}
    ex27: ----- 2. 필드를 고치면 content_id가 바뀐다 -----
    ex27: content_id 끝 {before=baf49b7d904303e8, after=0584fa496cf3ac88}
    ex27: set에 넣을 수 없다 {error=TypeError}
    ex27: ----- 3. 고른 필드로만 계산하기 -----
    ex27: label을 빼면 같다 {same=True}
    ex27: ----- 4. 구독한 뒤 요청을 고친다 -----
    ex27.tick: init {exchange=A}
    ex27: 구독의 요청 {exchange=A}
    ex27.tick: detached {exchange=A}

4단계에서 요청을 B로 고쳤는데도 detached는 A로 불린다. 사본이 없었다면 고친 요청의 content_id로
스테이지를 찾아, A 스테이지는 아무도 닫지 못한 채 계속 돌았을 것이다.

다음: ex28_serialization.py — 직렬화와 복원
"""

import asyncio
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    SourceRequest,
    get_model_id,
    get_model_uid,
    initialize,
)
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2

log = get_logger("ex27")
tick_log = get_logger("ex27.tick")


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    exchange: str
    label: str = ""
    """표시용 이름. 이것만 다른 요청도 `Domain`에게는 다른 요청이다."""


@initialize
def tick(req: TickReq) -> TickReq:
    tick_log.info("init", exchange=req.exchange)
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    while True:
        for symbol in sorted(symbols):
            yield DataModel(symbol=symbol)
        await asyncio.sleep(INTERVAL)


@tick.detached
async def _(ctx: TickReq):
    tick_log.info("detached", exchange=ctx.exchange)


# ===== 소비자 쪽 =====


def tail(identifier: str) -> str:
    """로그를 짧게 하려고 식별자의 끝 조각만 보인다."""

    return identifier.rsplit(":", 1)[-1]


async def ignore(data: DataModel) -> None:
    pass


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 식별자 셋과 가변 모델 ━━━━━━━━━━")

    log.info("----- 1. 내용이 같은 요청 둘 -----")
    a, b = TickReq(exchange="A"), TickReq(exchange="A")
    log.info("uid 끝 순번", a=tail(get_model_uid(a)), b=tail(get_model_uid(b)))
    assert get_model_uid(a) != get_model_uid(b)
    assert get_model_id(a) == get_model_id(b) == get_model_id(TickReq)  # 클래스로도 얻는다
    assert a.tr_content_id == b.tr_content_id

    log.info("----- 2. 필드를 고치면 content_id가 바뀐다 -----")
    before = a.tr_content_id
    a.exchange = "B"
    log.info("content_id 끝", before=tail(before), after=tail(a.tr_content_id))
    assert a.tr_content_id != before
    assert get_model_id(a) == get_model_id(b)  # 클래스는 그대로라 model_id도 그대로

    try:
        hash(a)  # set에 넣거나 dict 키로 쓸 때 부르는 것. pyright도 `{a}`는 미리 잡아 준다
    except TypeError as exc:
        log.info("set에 넣을 수 없다", error=type(exc).__name__)
    by_content = {r.tr_content_id: r for r in (a, b)}  # 키는 content_id로
    assert len(by_content) == 2

    log.info("----- 3. 고른 필드로만 계산하기 -----")
    c, d = TickReq(exchange="A", label="메인"), TickReq(exchange="A", label="백업")
    assert c.tr_content_id != d.tr_content_id  # Domain에게는 다른 요청
    assert c.compute_tr_content_id(exclude={"label"}) == d.compute_tr_content_id(exclude={"label"})
    log.info("label을 빼면 같다", same=True)

    log.info("----- 4. 구독한 뒤 요청을 고친다 -----")
    req = TickReq(exchange="A")
    original_id = req.tr_content_id
    async with domain.subscribe(req, ignore) as sub:
        await sub.update({"BTC/USD"})
        req.exchange = "B"  # 구독은 사본을 쓰므로 영향이 없다
        subscribed = sub.request  # 구독이 찍어 둔 사본. 타입도 `TickReq`다
        log.info("구독의 요청", exchange=subscribed.exchange)
        assert subscribed.exchange == "A"
        assert domain.get_shared_symbols(original_id) == {"BTC/USD"}
        assert domain.get_shared_symbols(req.tr_content_id) == set()
    # 블록을 벗어나면 처음 스테이지(exchange=A)가 닫힌다(detached).
    assert domain.get_shared_symbols(original_id) == set()
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
