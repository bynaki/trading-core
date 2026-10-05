"""ex28: 직렬화와 복원 — `tr_annotation` · `load_model` · `parse_dump` · `cast_model`

모델은 pydantic 모델이라 `model_dump_json()`으로 JSON이 된다. 이때 `tr_annotation`이 함께 실린다.
어느 모듈의 어느 클래스인지, 누가 만들었는지를 적은 꼬리표다.

    {"symbol": "BTC/USD", "price": 100.0,
     "tr_annotation": {"uid": ..., "model_id": ..., "model_type": "data",
                       "model_name": "TickData", "module_name": "...", "created_by": ...}}

받는 쪽(다른 프로세스, 로그서버 등)은 이 꼬리표로 모델을 되살린다.

| 함수 | 하는 일 |
| --- | --- |
| `load_model(json)` | `module_name`을 import하고 `model_name` 클래스를 찾아 되살린다 |
| `load_model(json, TickData)` | 주어진 클래스로 되살린다 |
| `parse_dump(json)` | 되살리지 않고 꼬리표만 검증한 dict를 준다. 클래스를 import할 수 없을 때 |
| `cast_model(data, TickData)` | 복사하지 않고 타입을 좁힌다. model_id가 정확히 같아야 한다 |

되살린 모델은 uid도 그대로다. 같은 모델이 프로세스를 건너도 추적할 수 있다. `created_by`는 그
모델을 만든 프로세스의 인스턴스 ID다. 기본값은 로그의 발신처(`service@host:pid`)에 무작위 꼬리를
붙인 것이고, 바꾸려면 프로그램이 시작하자마자, **모델을 하나라도 만들기 전에** `set_instance_id()`를
부른다. 이 예제가 돌 때는 이미 모델이 있으므로 `ModelError`가 난다.

배우는 것
- `model_dump_json()`에 `tr_annotation`이 실린다. 요청은 `model_type`이 `source` 등이다.
- `load_model()`은 클래스를 찾아 되살리고 uid를 유지한다.
- `cast_model()`은 model_id가 다른 클래스로는 좁히지 않는다(`ModelValidationError`).
- 인스턴스 ID는 첫 모델이 만들어질 때 정해진다.

실행
    uv run examples/ex28_serialization.py

기대 출력 (줄 앞의 레벨은 뺐다)
    ex28: ----- 1. 받은 데이터를 JSON으로 -----
    ex28: tr_annotation {model_type=data, name=TickData}
    ex28: ----- 2. load_model(): 클래스를 찾아 되살린다 -----
    ex28: 되살린 모델 {type=TickData, same_uid=True}
    ex28: ----- 3. parse_dump(): 클래스 없이 꼬리표만 읽는다 -----
    ex28: 꼬리표 {model_type=data, created_by_me=True}
    ex28: ----- 4. cast_model(): model_id가 정확히 같아야 좁힌다 -----
    ex28: 좁힐 수 없다 {error=ModelValidationError}
    ex28: ----- 5. set_instance_id(): 모델을 만든 뒤에는 바꿀 수 없다 -----
    ex28: 바꿀 수 없다 {error=ModelError}

`load_model(text)`는 꼬리표의 `module_name`을 import한다. 직접 실행하면 `__main__`, `main.py`로
돌리면 `ex28_serialization`이다. 받는 쪽도 그 이름으로 import할 수 있어야 한다. 그럴 수 없으면
클래스를 직접 주거나(`load_model(text, TickData)`) `parse_dump()`로 꼬리표만 읽는다.

다음: ex29_logging.py — 로그 모듈
"""

import asyncio
import json
from pathlib import Path

from trading_core import (
    DataModel,
    Domain,
    ModelError,
    SourceRequest,
    cast_model,
    get_instance_id,
    get_model_created_by,
    get_model_id,
    get_model_type,
    get_model_uid,
    initialize,
    load_model,
    parse_dump,
    set_instance_id,
)
from trading_core.exceptions import ModelValidationError
from trading_core.logger import configure, get_logger

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
INTERVAL = 0.2

log = get_logger("ex28")


# ===== binder 쪽 =====


class TickReq(SourceRequest):
    pass


class TickData(DataModel):
    price: float


class OtherData(DataModel):
    price: float
    """필드가 같아도 클래스가 다르면 model_id가 다르다."""


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


# ===== 소비자 쪽 =====


async def run_ex(domain: Domain) -> None:
    log.info("━━━━━━━━━━ 시작: 직렬화와 복원 ━━━━━━━━━━")

    log.info("----- 1. 받은 데이터를 JSON으로 -----")
    async with domain.stream(TickReq(), {"BTC/USD"}) as stream:
        received = cast_model(await anext(stream), TickData)  # 하나만 받는다
    text = received.model_dump_json()  # 이 문자열을 다른 프로세스로 보낸다고 하자
    annotation = json.loads(text)["tr_annotation"]
    log.info("tr_annotation", model_type=annotation["model_type"], name=annotation["model_name"])
    assert annotation["model_type"] == "data"
    assert get_model_type(TickReq()) == "source"  # 요청은 등록된 종류가 실린다

    log.info("----- 2. load_model(): 클래스를 찾아 되살린다 -----")
    loaded = load_model(text)
    log.info(
        "되살린 모델",
        type=type(loaded).__name__,
        same_uid=get_model_uid(loaded) == get_model_uid(received),
    )
    assert isinstance(loaded, TickData)
    assert loaded.price == received.price
    assert get_model_uid(loaded) == get_model_uid(received)  # uid도 그대로
    assert load_model(text, TickData).price == received.price  # 클래스를 직접 줘도 된다

    log.info("----- 3. parse_dump(): 클래스 없이 꼬리표만 읽는다 -----")
    dump = parse_dump(text)
    log.info(
        "꼬리표",
        model_type=get_model_type(dump),
        created_by_me=get_model_created_by(dump) == get_instance_id(),
    )
    assert get_model_id(dump) == get_model_id(TickData)
    assert get_model_created_by(dump) == get_instance_id()

    log.info("----- 4. cast_model(): model_id가 정확히 같아야 좁힌다 -----")
    try:
        cast_model(loaded, OtherData)
    except ModelValidationError as exc:
        log.warning("좁힐 수 없다", error=type(exc).__name__)
    else:
        raise AssertionError("OtherData로 좁혀지면 안 된다")

    log.info("----- 5. set_instance_id(): 모델을 만든 뒤에는 바꿀 수 없다 -----")
    try:
        set_instance_id("trader-kr-01")
    except ModelError as exc:
        log.warning("바꿀 수 없다", error=type(exc).__name__)
    else:
        raise AssertionError("이미 정해진 인스턴스 ID는 바뀌면 안 된다")
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
