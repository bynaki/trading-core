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
    data = json.dumps(make_dump()).encode()

    model = validate_model(data, ValidationModel)

    assert isinstance(model, ValidationModel)
    assert model.value == 42


def test_validate_model_revalidates_dictionary_annotation() -> None:
    dump = make_dump()
    annotation: Any = dump["tr_annotation"]
    annotation["id"] = 123

    with pytest.raises(ModelValidateError):
        validate_model(dump, ValidationModel)


def test_validate_model_rejects_module_attribute_that_is_not_a_model() -> None:
    dump = make_dump()
    module = ModuleType("invalid_models")
    setattr(module, ValidationModel.__name__, object())

    with pytest.raises(ModelValidateError, match="유효한 모델 클래스"):
        validate_model(dump, module)


def test_cast_model_returns_same_instance() -> None:
    data = ValidationModel(value=42)

    result = cast_model(data, ValidationModel)

    assert result is data


def test_cast_model_rejects_different_model_id() -> None:
    data = ValidationSubclass(value=42)

    with pytest.raises(ModelValidateError, match="모델 ID"):
        cast_model(data, ValidationModel)
