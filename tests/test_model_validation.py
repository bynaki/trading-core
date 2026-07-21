"""직렬화된 모델의 복원 검증과 안전한 타입 축소 동작을 테스트한다."""

import json
from types import ModuleType
from typing import Any

import pytest

from trading_core import DataModel, cast_model, validate_dump, validate_model
from trading_core.exceptions import ModelValidateError
from trading_core.model import DataDump


class ValidationModel(DataModel):
    value: int


class ValidationSubclass(ValidationModel):
    pass


def make_dump() -> DataDump:
    return validate_dump(ValidationModel(value=42).model_dump(mode="json"))


def test_validate_model_accepts_bytes_with_explicit_model() -> None:
    """명시한 모델 타입과 일치하는 bytes 덤프를 해당 모델로 복원한다."""
    data = json.dumps(make_dump()).encode()

    model = validate_model(data, ValidationModel)

    assert isinstance(model, ValidationModel)
    assert model.value == 42


def test_validate_model_revalidates_dictionary_annotation() -> None:
    """딕셔너리 덤프도 annotation 구조를 다시 검증하여 잘못된 값을 거부한다."""
    dump = make_dump()
    annotation: Any = dump["tr_annotation"]
    annotation["id"] = 123

    with pytest.raises(ModelValidateError):
        validate_model(dump, ValidationModel)


def test_validate_model_rejects_module_attribute_that_is_not_a_model() -> None:
    """모듈에서 찾은 동명 속성이 모델 클래스가 아니면 복원을 거부한다."""
    dump = make_dump()
    module = ModuleType("invalid_models")
    setattr(module, ValidationModel.__name__, object())

    with pytest.raises(ModelValidateError, match="유효한 모델 클래스"):
        validate_model(dump, module)


def test_cast_model_returns_same_instance() -> None:
    """model ID가 일치하면 복사 없이 기존 인스턴스의 타입만 좁힌다."""
    data = ValidationModel(value=42)

    result = cast_model(data, ValidationModel)

    assert result is data


def test_cast_model_rejects_different_model_id() -> None:
    """상속 관계가 있어도 model ID가 다른 인스턴스로는 타입을 좁히지 않는다."""
    data = ValidationSubclass(value=42)

    with pytest.raises(ModelValidateError, match="모델 ID"):
        cast_model(data, ValidationModel)
