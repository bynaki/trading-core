import json
import re
from collections.abc import Callable, Coroutine, Mapping
from importlib import import_module
from inspect import signature
from types import ModuleType
from typing import (
    Any,
    ClassVar,
    Literal,
    Protocol,
    Self,
    TypedDict,
    cast,
    overload,
)

from pydantic import BaseModel, PrivateAttr, TypeAdapter, computed_field
from pydantic.main import IncEx

from .exceptions import ModelError, ModelValidateError
from .helper import generate_digest, generate_id, verify_module

_origin_name: str = ""


def set_origin_name(name: str) -> None:
    global _origin_name
    if _origin_name:
        raise ModelError(f"이미 출처 이름이 있다. - '{_origin_name}'")
    _origin_name = name


def get_origin_name() -> str:
    global _origin_name
    if not _origin_name:
        _origin_name = generate_id(12)
    return _origin_name


class TrAnnotation(TypedDict):
    id: str
    model_id: str
    model_type: str
    model_name: str
    module_name: str
    generated_origin: str


type ModelType = Literal[
    "base", "unregistered", "generator", "dependent_generator", "instanter", "data"
]

_model_type_list = ("base", "unregistered", "generator", "dependent_generator", "instanter", "data")


class TrBaseModel(BaseModel):
    _tr_model_id: ClassVar[str] = "__none__"  # 클래스 정의 시 자동 생성됨
    _tr_model_type: ClassVar[ModelType] = "base"
    # ClassVar를 사용해 Pydantic이 이 변수를 필드로 인식하지 않게 합니다.
    _tr_counter: ClassVar[int] = 0
    _tr_id: str = PrivateAttr(default="")
    _tr_origin_annotation: TrAnnotation | None = PrivateAttr(default=None)
    _tr_cached_id: str | None = PrivateAttr(default=None)  # 내부에서만 쓰는 캐시 (직렬화 시 숨겨짐)

    def __init__(self, **data: Any):
        super().__init__(**data)
        self._tr_origin_annotation = data.get("tr_annotation")
        if self._tr_origin_annotation:
            self._tr_id = self._tr_origin_annotation["id"]
        else:
            self.__class__._tr_counter += 1
            self._tr_id = (
                f"{get_model_name(self)}@{get_module_name(self)}"
                f":{get_origin_name()}:{self.__class__._tr_counter}"
            )

    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        # 새로운 하위 클래스가 생성될 때마다 해당 클래스만의 카운터를 0으로 초기화합니다.
        cls._tr_counter = 0
        module_name = verify_module(cls).__name__
        class_name = cls.__name__
        # pydantic의 model_fields 에는 정의된 필드들이 들어있음
        #
        field_names = sorted(cls.model_fields.keys())
        # 추가로 메서드/클래스 변수 등을 포함하고 싶다면:
        # attrs = sorted([k for k in cls.__dict__.keys() if not k.startswith("_")])
        # 여기서는 모델 필드만 사용
        raw_str = f"{class_name}@{module_name}:{','.join(field_names)}"
        # digest = hashlib.sha256(raw_str.encode()).hexdigest()[:16]
        digest = generate_digest(raw_str)
        cls._tr_model_id = f"{class_name}@{module_name}:{digest}"

    @property
    def _tr_content_id(self) -> str:
        """모듈명 + 클래스명 + 내용 기반 고유 ID 생성"""
        cached: str | None = getattr(self, "_tr_cached_id", None)
        if cached is None:
            # prefix = f"{self.__class__.__module__}@{self.__class__.__name__}"
            # content = json.dumps(
            #     self.model_dump(
            #         mode="json", exclude_none=True, exclude={"tr_annotation"}
            #     ),
            #     sort_keys=True,
            #     ensure_ascii=False,
            # )
            # digest = generate_digest(content)
            # cached = f"{prefix}:{digest}"
            cached = self.get_tr_content_id()
            object.__setattr__(self, "_tr_cached_id", cached)
        return cached

    def get_tr_content_id(self, include: IncEx | None = None, exclude: IncEx | None = None) -> str:
        prefix = f"{self.__class__.__module__}@{self.__class__.__name__}"
        # exclude가 None이면 빈 세트로 초기화하고, tr_annotation 추가
        exclude_set: Any
        if exclude is None:
            exclude_set = {"tr_annotation"}
        elif isinstance(exclude, set):
            exclude_set = exclude | {"tr_annotation"}
        elif isinstance(exclude, dict):
            exclude_set = set(exclude.keys()) | {"tr_annotation"}
        else:
            exclude_set = {"tr_annotation"}

        content = json.dumps(
            self.model_dump(mode="json", exclude_none=True, include=include, exclude=exclude_set),
            sort_keys=True,
            ensure_ascii=False,
        )
        digest = generate_digest(content)
        return f"{prefix}:{digest}"

    def get_tr_annotation(self) -> TrAnnotation:
        if self._tr_origin_annotation:
            return self._tr_origin_annotation
        else:
            return {
                "id": self._tr_id,
                "model_id": self._tr_model_id,
                "model_type": self._tr_model_type,
                "model_name": get_model_name(self),
                "module_name": get_module_name(self),
                "generated_origin": get_origin_name(),
            }

    @computed_field
    def tr_annotation(self) -> TrAnnotation:
        return self.get_tr_annotation()

    def __setattr__(self, key: str, value: Any) -> None:
        """값 변경 시 캐시 무효화"""
        if key == "_tr_cached_id":
            object.__setattr__(self, key, value)
            return
        super().__setattr__(key, value)
        # 캐시된 ID가 있으면 초기화 (None으로 설정)
        if getattr(self, "_tr_cached_id", None) is not None:
            object.__setattr__(self, "_tr_cached_id", None)


class DataDump(TypedDict):
    tr_annotation: TrAnnotation


_tr_annotation_adapter = TypeAdapter(TrAnnotation)


# ===== Helper Functions =====


def get_model_inst_id(data: TrBaseModel | DataDump) -> str:
    if isinstance(data, TrBaseModel):
        return data._tr_id  # type: ignore
    return data["tr_annotation"]["id"]


def get_model_type(data: TrBaseModel | type[TrBaseModel] | DataDump) -> ModelType:
    if isinstance(data, dict):
        try:
            model_type = data["tr_annotation"]["model_type"]
            if model_type in _model_type_list:
                return model_type
            raise ModelError(f"기대한 'model type' 이 아니다. - {model_type}")
        except Exception as e:
            raise ModelError("'model_type' 요소가 없다.") from e
    return data._tr_model_type


def get_model_id(data: TrBaseModel | type[TrBaseModel] | DataDump) -> str:
    if isinstance(data, dict):
        return data["tr_annotation"]["model_id"]
    return data._tr_model_id  # type: ignore


def get_module_name(data: TrBaseModel | DataDump) -> str:
    if isinstance(data, TrBaseModel):
        return re.split(r"[@:]", get_model_id(data))[1]
    return data["tr_annotation"]["module_name"]


def get_model_name(data: TrBaseModel | DataDump) -> str:
    if isinstance(data, TrBaseModel):
        return re.split(r"[@:]", get_model_id(data))[0]
    return data["tr_annotation"]["model_name"]


def get_model_generated_origin(data: TrBaseModel | DataDump) -> str:
    if isinstance(data, TrBaseModel):
        return re.split(r"[@::]", get_model_inst_id(data))[2]
    return data["tr_annotation"]["generated_origin"]


# Treq = TypeVar("Treq", bound="RequestModel")
# Treq2 = TypeVar("Treq2", bound="RequestModel")
# Tget = TypeVar("Tget", bound="DataModel")
# Tput = TypeVar("Tput", bound="DataModel")


class Runnable[Tin: DataModel, Tout: DataModel](Protocol):
    async def invoke(self, input: Tin) -> Tout | None: ...


class Sequence[Treq: BaseReqModel]:
    def __init__(self, pre: Sequence[Treq], *steps: Runnable):
        self._req = pre.require
        self._symbol = pre.symbol
        self._steps = steps
        # self._joins: set[Sequence[RequestModel]] = set()

    def __or__(self, other: Runnable) -> Sequence[Treq]:
        return Sequence(self, *self._steps, other)

    @property
    def require(self) -> Treq:
        return self._req

    @property
    def symbol(self) -> str:
        return self._symbol

    async def invoke(self, input: DataModel) -> DataModel | None:
        data = input
        for step in self._steps:
            data = await step.invoke(data)
            if not data:
                return
        # if not data.get_tr_req_content_id():
        #     data._tr_req_content_id = self._req.get_tr_content_id()
        return data
        # if not self._joins:
        #     raise SequenceError("'Join'할게 없으면 아웃풋 데이터는 'None'이어야 한다.")
        # joins = list(self._joins)
        # results: list[None | BaseException] = await gather(
        #     *[s.invoke(data) for s in joins], return_exceptions=True
        # )
        # errors: list[Exception] = []
        # removing: set[Sequence[RequestModel]] = set()
        # for i, error in enumerate(results):
        #     if isinstance(error, ExceptionGroup):
        #         # group = cast(ExceptionGroup[Exception], error)
        #         errors.extend(error.exceptions)
        #     elif isinstance(error, Exception):
        #         errors.append(error)
        #     removing.add(joins[i])
        # self._joins -= removing
        # if not self._joins:
        #     errors.append(SequenceError("더이상 'Join'할게 없다."))
        # if errors:
        #     raise ExceptionGroup("Sequence Error!!", errors)

    def _set_req_symbol(self, req_symbol: str):
        self._req_symbol = req_symbol


class RequireSequence[Treq: BaseReqModel](Sequence):
    def __init__(self, require: Treq, symbol: str):
        self._req = require
        self._symbol = symbol
        self._steps = ()
        # self._joins: set[Sequence[RequestModel]] = set()


class BaseReqModel(TrBaseModel):
    _tr_model_type: ClassVar[ModelType] = "unregistered"
    # _tr_request_list: ClassVar[list[Callable[[Self], RequestModel]]] = []

    def __call__(self, symbol: str) -> Sequence[Self]:
        return RequireSequence(self, symbol)


class GenerateModel(BaseReqModel): ...


class DependentModel(BaseReqModel):
    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        cls._tr_require_cb: RequireCbWithSym[Self] | None = None

    @classmethod
    def _set_require(cls, cb: RequireCb | RequireCbWithSym) -> None:
        """require 콜백을 `RequireCbWithSym` 형태로 정규화해 보관한다.

        `RequireCb`(요청만 받는 형태)로 등록하면 심볼 집합을 그대로 흘려보내는
        래퍼로 감싼다. 덕분에 소비처는 두 형태를 구분할 필요가 없다.
        """
        if _takes_symbols(cb):
            cls._tr_require_cb = cast("RequireCbWithSym[Self]", cb)
            return
        plain = cast("RequireCb[Self]", cb)

        def with_sym(
            req: Any, symbols: set[str]
        ) -> tuple[GenerateModel | DependentModel, set[str]]:
            return plain(req), symbols

        cls._tr_require_cb = with_sym

    @property
    def tr_require(self) -> GenerateModel | DependentModel:
        callback = type(self)._tr_require_cb
        if callback is None:
            raise ModelError(f"'require' 정의가 필요하다. - {get_model_id(self)}")
        return callback(self, set[str]())[0]

    def get_tr_require_with_symbol(
        self, symbols: set[str]
    ) -> tuple[GenerateModel | DependentModel, set[str]]:
        callback = type(self)._tr_require_cb
        if callback is None:
            raise ModelError(f"'require' 정의가 필요하다. - {get_model_id(self)}")
        return callback(self, set(symbols))

    @overload
    @classmethod
    def require[Treq: GenerateModel | DependentModel](
        cls, cb: Callable[[Self], Treq]
    ) -> Callable[[Self], Treq]: ...

    @overload
    @classmethod
    def require[Treq: GenerateModel | DependentModel](
        cls, cb: Callable[[Self, set[str]], tuple[Treq, set[str]]]
    ) -> Callable[[Self, set[str]], tuple[Treq, set[str]]]: ...

    @classmethod
    def require(cls, cb: RequireCb[Self] | RequireCbWithSym[Self]) -> Any:
        """상위 요청을 만드는 require 콜백을 등록한다.

        요청만 받는 형태(`RequireCb`)와 심볼 집합까지 받아 변형하는 형태
        (`RequireCbWithSym`) 둘 다 받는다.
        """
        cls._set_require(cb)
        return cb


type RequireCb[Tdep: DependentModel] = Callable[[Tdep], GenerateModel | DependentModel]
type RequireCbWithSym[Tdep: DependentModel] = Callable[
    [Tdep, set[str]], tuple[GenerateModel | DependentModel, set[str]]
]


def _takes_symbols(cb: RequireCb | RequireCbWithSym) -> bool:
    """require 콜백이 심볼 집합까지 받는 형태(`RequireCbWithSym`)인지 판별한다.

    두 별칭은 런타임에 그냥 `Callable`이라 `isinstance`로 구분할 수 없다.
    위치 인자 개수로 판단한다.
    """
    params = [
        p
        for p in signature(cb).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    return len(params) >= 2


class RequestModel(BaseReqModel): ...


class DataModel(TrBaseModel):
    _tr_model_type: ClassVar[ModelType] = "data"
    symbol: str = ""
    _tr_req_content_id: str = ""

    def get_tr_req_content_id(self) -> str:
        return self._tr_req_content_id


def is_generate_model(req: BaseReqModel) -> bool:
    if isinstance(req, GenerateModel) and get_model_type(req) == "generator":
        return True
    return False


def is_dependent_model(req: BaseReqModel) -> bool:
    if isinstance(req, DependentModel) and get_model_type(req) == "dependent_generator":
        return True
    return False


def is_instant_model(req: BaseReqModel) -> bool:
    if isinstance(req, RequestModel) and get_model_type(req) == "instanter":
        return True
    return False


def validate_dump(json_data: str | bytes | Mapping[str, Any]) -> DataDump:
    try:
        raw: Any = dict(json_data) if isinstance(json_data, Mapping) else json.loads(json_data)
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ModelValidateError()
        raw["tr_annotation"] = _tr_annotation_adapter.validate_python(raw.get("tr_annotation"))
        return cast(DataDump, raw)
    except Exception as e:
        raise ModelValidateError("validate_dump() 유효성 검사 실패") from e


@overload
def validate_model(data: str | bytes | DataDump, refer: None = None) -> TrBaseModel: ...
@overload
def validate_model(data: str | bytes | DataDump, refer: ModuleType) -> TrBaseModel: ...
@overload
def validate_model[T: TrBaseModel](data: str | bytes | DataDump, refer: type[T]) -> T: ...


def validate_model[T: TrBaseModel](
    data: str | bytes | DataDump, refer: type[T] | ModuleType | None = None
) -> T | TrBaseModel:
    try:
        dump = validate_dump(data)
        annotation = dump["tr_annotation"]

        if isinstance(refer, type):
            model_type = refer
        else:
            module = refer or import_module(annotation["module_name"])
            candidate = getattr(module, annotation["model_name"], None)
            if not isinstance(candidate, type) or not issubclass(candidate, TrBaseModel):
                raise ModelValidateError(
                    f"유효한 모델 클래스를 찾을 수 없습니다: "
                    f"{module.__name__}.{annotation['model_name']}"
                )
            model_type = candidate

        return model_type.model_validate(dump)
    except ModelValidateError:
        raise
    except Exception as e:
        raise ModelValidateError("validate_model() 유효성 검사 실패") from e


def cast_model[T: TrBaseModel](data: TrBaseModel, cast_t: type[T]) -> T:
    """모델 인스턴스를 복사하지 않고 검증한 타입으로 좁힌다."""
    if not isinstance(data, TrBaseModel):
        raise ModelValidateError("data가 TrBaseModel 인스턴스가 아닙니다")
    if not isinstance(cast_t, type) or not issubclass(cast_t, TrBaseModel):
        raise ModelValidateError("cast_t가 TrBaseModel 하위 클래스가 아닙니다")
    data_model_id = get_model_id(data)
    cast_model_id = get_model_id(cast_t)
    if data_model_id != cast_model_id:
        raise ModelValidateError(f"모델 ID가 일치하지 않습니다: {data_model_id} != {cast_model_id}")
    return cast(T, data)


# close 되었다면 ClosedConnection 예외를 발생해야 한다.
# type Sender = Callable[[DataModel], Coroutine[Any, Any, None]]
type Sender[T] = Callable[[T], Coroutine[Any, Any, None]]
# class Sender(Protocol):
#     async def __call__(self, data: DataModel) -> None: ...

# async def close(self) -> None: ...


type Receiver[T] = Callable[[], Coroutine[Any, Any, T]]
# class Receiver(Protocol):
#     async def __call__(self) -> DataModel: ...


#     async def close(self) -> None: ...
