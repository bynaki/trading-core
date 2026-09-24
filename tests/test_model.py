"""모델 계층 명세 — 식별자 3종, 직렬화 왕복, `Pipeline`."""

import re
import sys

import pytest

from trading_core import (
    DataModel,
    ModelError,
    SourceRequest,
    cast_model,
    get_model_created_by,
    get_model_id,
    get_model_name,
    get_model_type,
    get_model_uid,
    get_module_name,
    load_model,
    model,
    parse_dump,
    set_instance_id,
)
from trading_core.exceptions import ModelValidationError
from trading_core.logger import Identity
from trading_core.model import get_instance_id

MODULE_NAME = __name__


class SampleReq(SourceRequest):
    """식별자 검증용 요청. binder를 등록하지 않아 계속 "unregistered"다."""

    name: str
    size: int = 1


class TwinReq(SourceRequest):
    """`SampleReq`와 필드 구성이 완전히 같은 다른 클래스."""

    name: str
    size: int = 1


class SampleData(DataModel):
    """직렬화 왕복 검증용 데이터."""

    value: str


# ===== model_id: 클래스 단위 정체성 =====


def test_model_id_is_shared_by_class_and_instance():
    """`model_id`는 클래스에 속하므로 인스턴스와 클래스가 같은 값을 낸다."""

    assert get_model_id(SampleReq) == get_model_id(SampleReq(name="a"))
    assert get_model_id(SampleReq(name="a")) == get_model_id(SampleReq(name="b", size=9))


def test_model_id_has_class_module_digest_shape():
    """`model_id`는 `클래스@모듈:digest` 꼴이다."""

    pattern = rf"SampleReq@{re.escape(MODULE_NAME)}:[0-9a-f]{{16}}"
    assert re.fullmatch(pattern, get_model_id(SampleReq))


def test_model_id_differs_between_classes_with_same_fields():
    """필드 구성이 같아도 클래스가 다르면 `model_id`가 다르다."""

    assert get_model_id(SampleReq) != get_model_id(TwinReq)


def test_model_name_and_module_name_come_from_model_id():
    """`get_model_name()` · `get_module_name()`은 `model_id`를 되짚어 읽는다."""

    req = SampleReq(name="a")
    assert get_model_name(req) == "SampleReq"
    assert get_module_name(req) == MODULE_NAME


# ===== uid: 인스턴스 단위 정체성 =====


def test_uid_is_unique_per_instance():
    """uid는 `클래스@모듈:인스턴스ID:순번`이고 인스턴스마다 다르다."""

    first = SampleReq(name="a")
    second = SampleReq(name="a")
    pattern = rf"SampleReq@{re.escape(MODULE_NAME)}:{re.escape(get_instance_id())}:\d+"
    assert re.fullmatch(pattern, get_model_uid(first))
    assert get_model_uid(first) != get_model_uid(second)


def test_uid_carries_instance_id():
    """uid의 세 번째 자리는 모델을 만든 프로세스의 인스턴스 ID다."""

    req = SampleReq(name="a")
    assert get_model_created_by(req) == get_instance_id()


def test_created_by_keeps_separators_in_instance_id(monkeypatch: pytest.MonkeyPatch):
    """인스턴스 ID에 `@`·`:`가 있어도 uid에서 인스턴스 ID를 그대로 되찾는다.

    기본 인스턴스 ID는 로그 발신처(`service@host:pid`)로 시작하므로 uid를 구분자로 쪼개면
    `service`만 남는다.
    """

    monkeypatch.setattr(model, "_instance_id", "trader-kr-01@ip-10-0-1-23:48213:3fa9c1")
    req = SampleReq(name="a")
    assert get_model_created_by(req) == "trader-kr-01@ip-10-0-1-23:48213:3fa9c1"
    assert get_model_created_by(req) == req.get_tr_annotation()["created_by"]


def test_default_instance_id_extends_the_log_identity(monkeypatch: pytest.MonkeyPatch):
    """기본 인스턴스 ID는 로그의 `instance_id`에 무작위 꼬리를 붙인 것이다.

    앞부분이 같아 로그와 모델을 이어 볼 수 있고, 꼬리가 달라 pid를 물려받은 프로세스끼리도
    uid가 겹치지 않는다.
    """

    identity = Identity(service="trader-kr-01", host="ip-10-0-1-23", pid=48213)
    monkeypatch.setattr(model, "get_identity", lambda: identity)
    tails: set[str] = set()
    for _ in range(2):
        monkeypatch.setattr(model, "_instance_id", "")
        head, tail = get_instance_id().rsplit(":", 1)
        assert head == "trader-kr-01@ip-10-0-1-23:48213"
        assert re.fullmatch(r"[0-9a-f]{6}", tail)
        tails.add(tail)
    assert len(tails) == 2  # 같은 발신처라도 꼬리가 다르다


def test_instance_id_cannot_be_replaced():
    """인스턴스 ID는 한 번 정해지면 바꿀 수 없다."""

    SampleReq(name="a")  # 모델을 만들면 인스턴스 ID가 자동 생성된다
    assert get_instance_id()
    with pytest.raises(ModelError):
        set_instance_id("another-instance")


# ===== content_id: 공유 단위 정체성 =====


def test_content_id_matches_for_equal_field_values():
    """필드 값이 같으면 서로 다른 인스턴스라도 같은 content_id를 갖는다."""

    first = SampleReq(name="a")
    second = SampleReq(name="a")
    assert get_model_uid(first) != get_model_uid(second)
    assert first.tr_content_id == second.tr_content_id


def test_content_id_ignores_defaulted_field_written_explicitly():
    """기본값을 명시해도 직렬화 내용이 같으므로 content_id가 같다."""

    implicit = SampleReq(name="a")
    explicit = SampleReq(name="a", size=1)
    assert implicit.tr_content_id == explicit.tr_content_id


def test_content_id_differs_for_different_values_and_classes():
    """값이 다르거나 클래스가 다르면 content_id도 달라진다."""

    assert SampleReq(name="a").tr_content_id != SampleReq(name="b").tr_content_id
    assert SampleReq(name="a").tr_content_id != TwinReq(name="a").tr_content_id


def test_content_id_cache_is_invalidated_on_mutation():
    """필드를 바꾸면 캐시된 content_id가 무효화된다."""

    req = SampleReq(name="a")
    before = req.tr_content_id
    assert req.tr_content_id == before  # 캐시가 같은 값을 돌려준다
    req.name = "b"
    assert req.tr_content_id != before


def test_content_id_cache_is_not_carried_into_an_updated_copy():
    """`model_copy(update=...)`한 복사본은 원본의 캐시가 아니라 자기 내용의 content_id를 낸다.

    pydantic은 private 값을 복사한 뒤 `update`를 `__setattr__` 없이 써 넣는다. `Domain`은 캐시된
    content_id로 공유 스테이지를 고르므로, 캐시가 따라오면 복사본이 원본의 스테이지에 붙는다.
    """

    req = SampleReq(name="a")
    original = req.tr_content_id  # 캐시를 채운다
    copied = req.model_copy(update={"name": "b"})
    assert copied.tr_content_id != original
    assert copied.tr_content_id == SampleReq(name="b").tr_content_id


def test_content_id_cache_is_not_a_field():
    """캐시는 private 저장소에 둔다. 필드(`__dict__`)에 섞이면 안 된다."""

    req = SampleReq(name="a")
    _ = req.tr_content_id
    assert set(req.__dict__) == {"name", "size"}


def test_content_id_can_exclude_fields():
    """`exclude`로 특정 필드를 빼면 그 필드가 달라도 같은 content_id가 된다."""

    first = SampleReq(name="a", size=1)
    second = SampleReq(name="a", size=2)
    assert first.compute_tr_content_id({"size"}) != second.compute_tr_content_id({"size"})
    assert first.compute_tr_content_id(exclude={"size"}) == second.compute_tr_content_id(
        exclude={"size"}
    )


# ===== model type =====


def test_model_type_of_unbound_request_is_unregistered():
    """binder에 등록되지 않은 요청은 "unregistered"다."""

    assert get_model_type(SampleReq) == "unregistered"
    assert get_model_type(SampleReq(name="a")) == "unregistered"


def test_data_model_type_and_default_symbol():
    """`DataModel`은 "data"이고 심볼 기본값은 빈 문자열이다."""

    assert get_model_type(SampleData) == "data"
    assert SampleData(value="v").symbol == ""


# ===== 직렬화 왕복 =====


def test_load_model_roundtrip_with_type_target():
    """타입을 지정한 왕복은 필드와 annotation을 모두 보존한다."""

    data = SampleData(symbol="BTC", value="v")
    restored = load_model(data.model_dump_json(), SampleData)
    assert isinstance(restored, SampleData)
    assert (restored.symbol, restored.value) == ("BTC", "v")
    assert get_model_uid(restored) == get_model_uid(data)
    assert restored.tr_content_id == data.tr_content_id


def test_load_model_roundtrip_without_target():
    """target을 생략하면 annotation의 모듈명으로 클래스를 되찾는다."""

    data = SampleData(symbol="ETH", value="v")
    restored = load_model(data.model_dump_json())
    assert isinstance(restored, SampleData)
    assert restored.symbol == "ETH"


def test_load_model_roundtrip_with_module_target():
    """모듈을 지정하면 그 모듈에서 클래스를 찾는다."""

    data = SampleData(symbol="XRP", value="v")
    restored = load_model(data.model_dump_json(), sys.modules[MODULE_NAME])
    assert isinstance(restored, SampleData)
    assert restored.symbol == "XRP"


def test_load_model_accepts_dump_mapping():
    """`parse_dump()`로 매핑을 검증해 넘겨도 같은 결과가 나온다."""

    data = SampleData(symbol="BTC", value="v")
    dump = parse_dump(data.model_dump(mode="json"))
    restored = load_model(dump, SampleData)
    assert restored.value == "v"


def test_parse_dump_rejects_broken_payload():
    """annotation이 없거나 JSON이 아니면 `ModelValidationError`."""

    with pytest.raises(ModelValidationError):
        parse_dump("json이 아니다")
    with pytest.raises(ModelValidationError):
        parse_dump('{"value": "v"}')


def test_load_model_rejects_unknown_model_name():
    """annotation이 가리키는 클래스가 없으면 `ModelValidationError`."""

    dump = parse_dump(SampleData(symbol="BTC", value="v").model_dump_json())
    dump["tr_annotation"]["model_name"] = "NoSuchModel"
    with pytest.raises(ModelValidationError):
        load_model(dump)


# ===== cast_model =====


def test_cast_model_returns_same_instance():
    """`cast_model()`은 복사하지 않고 같은 인스턴스를 좁혀서 돌려준다."""

    data = SampleData(symbol="BTC", value="v")
    assert cast_model(data, SampleData) is data


def test_cast_model_requires_exact_model_id():
    """`model_id`가 다르면(상속 관계여도) 좁힐 수 없다."""

    class ChildData(SampleData):
        """필드가 같아도 클래스가 다르면 `model_id`가 다르다."""

    data = SampleData(symbol="BTC", value="v")
    with pytest.raises(ModelValidationError):
        cast_model(data, ChildData)
    with pytest.raises(ModelValidationError):
        cast_model(data, SampleReq)


def test_cast_model_rejects_non_model_arguments():
    """모델이 아닌 값은 좁힐 수 없다."""

    with pytest.raises(ModelValidationError):
        cast_model("문자열", SampleData)  # type: ignore[arg-type]
    with pytest.raises(ModelValidationError):
        cast_model(SampleData(value="v"), str)  # type: ignore[type-var]


# ===== Pipeline =====


class Doubler:
    """입력 값을 두 배로 늘리는 `Runnable`."""

    async def invoke(self, input: DataModel) -> DataModel | None:
        data = cast_model(input, SampleData)
        return SampleData(symbol=data.symbol, value=data.value * 2)


class Blocker:
    """`None`을 돌려 파이프라인을 끊는 `Runnable`."""

    async def invoke(self, input: DataModel) -> DataModel | None:
        return None


def test_request_call_creates_pipeline():
    """요청을 심볼로 호출하면 그 심볼에 묶인 `Pipeline`이 나온다."""

    req = SampleReq(name="a")
    pipeline = req("BTC")
    assert pipeline.upstream is req
    assert pipeline.upstream_symbol == "BTC"


async def test_pipeline_runs_steps_in_order():
    """`|`로 이어 붙인 단계가 순서대로 실행된다."""

    pipeline = SampleReq(name="a")("BTC") | Doubler() | Doubler()
    result = await pipeline.invoke(SampleData(symbol="BTC", value="ab"))
    assert result is not None
    assert cast_model(result, SampleData).value == "abababab"


async def test_pipeline_stops_at_none():
    """중간 단계가 `None`을 돌려주면 거기서 끝난다."""

    pipeline = SampleReq(name="a")("BTC") | Blocker() | Doubler()
    assert await pipeline.invoke(SampleData(symbol="BTC", value="ab")) is None
