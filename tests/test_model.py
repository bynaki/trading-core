"""모델 계층 명세 — 식별자 3종, 직렬화 왕복, `Sequence`."""

import re
import sys

import pytest

from trading_core import (
    DataModel,
    GenerateModel,
    ModelError,
    cast_model,
    get_model_generated_origin,
    get_model_id,
    get_model_inst_id,
    get_model_name,
    get_model_type,
    get_module_name,
    set_origin_name,
    validate_dump,
    validate_model,
)
from trading_core.exceptions import ModelValidateError
from trading_core.model import get_origin_name

MODULE_NAME = __name__


class SampleReq(GenerateModel):
    """식별자 검증용 요청. binder를 등록하지 않아 계속 "unregistered"다."""

    name: str
    size: int = 1


class TwinReq(GenerateModel):
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


# ===== instance id: 인스턴스 단위 정체성 =====


def test_instance_id_is_unique_per_instance():
    """instance id는 `클래스@모듈:출처:순번`이고 인스턴스마다 다르다."""

    first = SampleReq(name="a")
    second = SampleReq(name="a")
    pattern = rf"SampleReq@{re.escape(MODULE_NAME)}:[0-9a-f]+:\d+"
    assert re.fullmatch(pattern, get_model_inst_id(first))
    assert get_model_inst_id(first) != get_model_inst_id(second)


def test_instance_id_carries_origin_name():
    """instance id의 세 번째 자리는 이 프로세스의 출처 이름이다."""

    req = SampleReq(name="a")
    assert get_model_generated_origin(req) == get_origin_name()


def test_origin_name_cannot_be_replaced():
    """출처 이름은 한 번 정해지면 바꿀 수 없다."""

    SampleReq(name="origin")  # 인스턴스를 만들면 출처 이름이 자동 생성된다
    assert get_origin_name()
    with pytest.raises(ModelError):
        set_origin_name("another-origin")


# ===== content_id: 공유 단위 정체성 =====


def test_content_id_matches_for_equal_field_values():
    """필드 값이 같으면 서로 다른 인스턴스라도 같은 content_id를 갖는다."""

    first = SampleReq(name="a")
    second = SampleReq(name="a")
    assert get_model_inst_id(first) != get_model_inst_id(second)
    assert first.get_tr_content_id() == second.get_tr_content_id()


def test_content_id_ignores_defaulted_field_written_explicitly():
    """기본값을 명시해도 직렬화 내용이 같으므로 content_id가 같다."""

    implicit = SampleReq(name="a")
    explicit = SampleReq(name="a", size=1)
    assert implicit.get_tr_content_id() == explicit.get_tr_content_id()


def test_content_id_differs_for_different_values_and_classes():
    """값이 다르거나 클래스가 다르면 content_id도 달라진다."""

    assert SampleReq(name="a").get_tr_content_id() != SampleReq(name="b").get_tr_content_id()
    assert SampleReq(name="a").get_tr_content_id() != TwinReq(name="a").get_tr_content_id()


def test_content_id_cache_is_invalidated_on_mutation():
    """필드를 바꾸면 캐시된 content_id가 무효화된다."""

    req = SampleReq(name="a")
    before = req._tr_content_id
    assert req._tr_content_id == before  # 캐시가 같은 값을 돌려준다
    req.name = "b"
    assert req._tr_content_id != before


def test_content_id_can_exclude_fields():
    """`exclude`로 특정 필드를 빼면 그 필드가 달라도 같은 content_id가 된다."""

    first = SampleReq(name="a", size=1)
    second = SampleReq(name="a", size=2)
    assert first.get_tr_content_id({"size"}) != second.get_tr_content_id({"size"})
    assert first.get_tr_content_id(exclude={"size"}) == second.get_tr_content_id(exclude={"size"})


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


def test_validate_model_roundtrip_with_type_refer():
    """타입을 지정한 왕복은 필드와 annotation을 모두 보존한다."""

    data = SampleData(symbol="BTC", value="v")
    restored = validate_model(data.model_dump_json(), SampleData)
    assert isinstance(restored, SampleData)
    assert (restored.symbol, restored.value) == ("BTC", "v")
    assert get_model_inst_id(restored) == get_model_inst_id(data)
    assert restored.get_tr_content_id() == data.get_tr_content_id()


def test_validate_model_roundtrip_without_refer():
    """refer를 생략하면 annotation의 모듈명으로 클래스를 되찾는다."""

    data = SampleData(symbol="ETH", value="v")
    restored = validate_model(data.model_dump_json())
    assert isinstance(restored, SampleData)
    assert restored.symbol == "ETH"


def test_validate_model_roundtrip_with_module_refer():
    """모듈을 지정하면 그 모듈에서 클래스를 찾는다."""

    data = SampleData(symbol="XRP", value="v")
    restored = validate_model(data.model_dump_json(), sys.modules[MODULE_NAME])
    assert isinstance(restored, SampleData)
    assert restored.symbol == "XRP"


def test_validate_model_accepts_dump_mapping():
    """`validate_dump()`으로 매핑을 검증해 넘겨도 같은 결과가 나온다."""

    data = SampleData(symbol="BTC", value="v")
    dump = validate_dump(data.model_dump(mode="json"))
    restored = validate_model(dump, SampleData)
    assert restored.value == "v"


def test_validate_dump_rejects_broken_payload():
    """annotation이 없거나 JSON이 아니면 `ModelValidateError`."""

    with pytest.raises(ModelValidateError):
        validate_dump("json이 아니다")
    with pytest.raises(ModelValidateError):
        validate_dump('{"value": "v"}')


def test_validate_model_rejects_unknown_model_name():
    """annotation이 가리키는 클래스가 없으면 `ModelValidateError`."""

    dump = validate_dump(SampleData(symbol="BTC", value="v").model_dump_json())
    dump["tr_annotation"]["model_name"] = "NoSuchModel"
    with pytest.raises(ModelValidateError):
        validate_model(dump)


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
    with pytest.raises(ModelValidateError):
        cast_model(data, ChildData)
    with pytest.raises(ModelValidateError):
        cast_model(data, SampleReq)


def test_cast_model_rejects_non_model_arguments():
    """모델이 아닌 값은 좁힐 수 없다."""

    with pytest.raises(ModelValidateError):
        cast_model("문자열", SampleData)  # type: ignore[arg-type]
    with pytest.raises(ModelValidateError):
        cast_model(SampleData(value="v"), str)  # type: ignore[type-var]


# ===== Sequence =====


class Doubler:
    """입력 값을 두 배로 늘리는 `Runnable`."""

    async def invoke(self, input: DataModel) -> DataModel | None:
        data = cast_model(input, SampleData)
        return SampleData(symbol=data.symbol, value=data.value * 2)


class Blocker:
    """`None`을 돌려 시퀀스를 끊는 `Runnable`."""

    async def invoke(self, input: DataModel) -> DataModel | None:
        return None


def test_request_call_creates_sequence():
    """요청을 심볼로 호출하면 그 심볼에 묶인 `Sequence`가 나온다."""

    req = SampleReq(name="a")
    seq = req("BTC")
    assert seq.require is req
    assert seq.symbol == "BTC"


async def test_sequence_runs_steps_in_order():
    """`|`로 이어 붙인 단계가 순서대로 실행된다."""

    seq = SampleReq(name="a")("BTC") | Doubler() | Doubler()
    result = await seq.invoke(SampleData(symbol="BTC", value="ab"))
    assert result is not None
    assert cast_model(result, SampleData).value == "abababab"


async def test_sequence_stops_at_none():
    """중간 단계가 `None`을 돌려주면 거기서 끝난다."""

    seq = SampleReq(name="a")("BTC") | Blocker() | Doubler()
    assert await seq.invoke(SampleData(symbol="BTC", value="ab")) is None
