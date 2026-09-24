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

from .exceptions import ModelError, ModelValidationError
from .ids import generate_digest, generate_id, verify_module
from .logger import get_identity

_instance_id: str = ""

_INSTANCE_TAIL_LENGTH = 6
"""기본 인스턴스 ID 끝에 붙이는 무작위 꼬리의 길이(16진수 글자 수)."""


def set_instance_id(instance_id: str) -> None:
    """이 프로세스의 인스턴스 ID를 정한다. 모델의 uid와 `created_by`에 실린다.

    모델을 하나라도 만들기 전에 불러야 한다. 처음 만든 모델이 기본값을 정해 버린다.
    """
    global _instance_id
    if _instance_id:
        raise ModelError(f"이미 인스턴스 ID가 있다. - '{_instance_id}'")
    _instance_id = instance_id


def get_instance_id() -> str:
    """이 프로세스의 인스턴스 ID.

    정하지 않았으면 처음 부를 때 로그 발신처의 `instance_id`(`service@host:pid`)에 무작위 꼬리를
    붙여 만든다(예: `trader-kr-01@ip-10-0-1-23:48213:3fa9c1`). 앞부분이 로그와 같아 로그와 모델을
    이어 볼 수 있고, 꼬리는 재시작한 프로세스가 pid를 물려받아도 uid가 겹치지 않게 한다.
    `service_name`을 바꿔 `configure()`할 계획이면 모델을 만들기 전에 구성한다.
    """
    global _instance_id
    if not _instance_id:
        _instance_id = f"{get_identity().instance_id}:{generate_id(_INSTANCE_TAIL_LENGTH)}"
    return _instance_id


class TrAnnotation(TypedDict):
    uid: str
    model_id: str
    model_type: str
    model_name: str
    module_name: str
    created_by: str


type ModelType = Literal["base", "unregistered", "source", "derived", "session", "data"]

_MODEL_TYPES = ("base", "unregistered", "source", "derived", "session", "data")


class TrBaseModel(BaseModel):
    _tr_model_id: ClassVar[str] = "__none__"  # 클래스 정의 시 자동 생성됨
    _tr_model_type: ClassVar[ModelType] = "base"
    # ClassVar를 사용해 Pydantic이 이 변수를 필드로 인식하지 않게 합니다.
    _tr_uid_seq: ClassVar[int] = 0
    _tr_uid: str = PrivateAttr(default="")
    _tr_loaded_annotation: TrAnnotation | None = PrivateAttr(default=None)
    # 내부에서만 쓰는 캐시 (직렬화 시 숨겨짐)
    _tr_cached_content_id: str | None = PrivateAttr(default=None)

    def __init__(self, **data: Any):
        super().__init__(**data)
        self._tr_loaded_annotation = data.get("tr_annotation")
        if self._tr_loaded_annotation:
            self._tr_uid = self._tr_loaded_annotation["uid"]
        else:
            self.__class__._tr_uid_seq += 1
            self._tr_uid = (
                f"{get_model_name(self)}@{get_module_name(self)}"
                f":{get_instance_id()}:{self.__class__._tr_uid_seq}"
            )

    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        # 새로운 하위 클래스가 생성될 때마다 해당 클래스만의 순번을 0으로 초기화합니다.
        cls._tr_uid_seq = 0
        module_name = verify_module(cls).__name__
        class_name = cls.__name__
        # pydantic의 model_fields 에는 정의된 필드들이 들어있음. 여기서는 모델 필드만 사용
        field_names = sorted(cls.model_fields.keys())
        raw_str = f"{class_name}@{module_name}:{','.join(field_names)}"
        digest = generate_digest(raw_str)
        cls._tr_model_id = f"{class_name}@{module_name}:{digest}"

    @property
    def tr_content_id(self) -> str:
        """모델 타입 + 내용 기반 ID. 값이 바뀌기 전까지 캐시한다."""
        cached = self._tr_cached_content_id
        if cached is None:
            cached = self.compute_tr_content_id()
            # pydantic의 `__setattr__`을 거쳐야 필드(`__dict__`)가 아니라 private 저장소에 들어간다.
            super().__setattr__("_tr_cached_content_id", cached)
        return cached

    def compute_tr_content_id(
        self, include: IncEx | None = None, exclude: IncEx | None = None
    ) -> str:
        """content_id를 캐시 없이 계산한다. `include`/`exclude`로 반영할 필드를 고른다."""
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
        if self._tr_loaded_annotation:
            return self._tr_loaded_annotation
        else:
            return {
                "uid": self._tr_uid,
                "model_id": self._tr_model_id,
                "model_type": self._tr_model_type,
                "model_name": get_model_name(self),
                "module_name": get_module_name(self),
                "created_by": get_instance_id(),
            }

    @computed_field
    def tr_annotation(self) -> TrAnnotation:
        return self.get_tr_annotation()

    def __setattr__(self, key: str, value: Any) -> None:
        """값 변경 시 캐시 무효화"""
        super().__setattr__(key, value)
        if key != "_tr_cached_content_id" and self._tr_cached_content_id is not None:
            super().__setattr__("_tr_cached_content_id", None)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """복사본의 content_id 캐시를 비운다.

        pydantic은 private 값(캐시 포함)을 그대로 복사한 뒤 `update`를 `__setattr__` 없이 필드에
        써 넣는다. 캐시를 비우지 않으면 필드가 바뀐 복사본이 원본의 content_id를 돌려준다.
        """
        copied = super().model_copy(update=update, deep=deep)
        copied._tr_cached_content_id = None
        return copied


class ModelDump(TypedDict):
    tr_annotation: TrAnnotation


_tr_annotation_adapter = TypeAdapter(TrAnnotation)


# ===== Helper Functions =====


def get_model_uid(data: TrBaseModel | ModelDump) -> str:
    if isinstance(data, TrBaseModel):
        return data._tr_uid  # type: ignore
    return data["tr_annotation"]["uid"]


def get_model_type(data: TrBaseModel | type[TrBaseModel] | ModelDump) -> ModelType:
    if isinstance(data, dict):
        try:
            model_type = data["tr_annotation"]["model_type"]
            if model_type in _MODEL_TYPES:
                return model_type
            raise ModelError(f"기대한 'model type' 이 아니다. - {model_type}")
        except Exception as e:
            raise ModelError("'model_type' 요소가 없다.") from e
    return data._tr_model_type


def get_model_id(data: TrBaseModel | type[TrBaseModel] | ModelDump) -> str:
    if isinstance(data, dict):
        return data["tr_annotation"]["model_id"]
    return data._tr_model_id  # type: ignore


def get_module_name(data: TrBaseModel | ModelDump) -> str:
    if isinstance(data, TrBaseModel):
        return re.split(r"[@:]", get_model_id(data))[1]
    return data["tr_annotation"]["module_name"]


def get_model_name(data: TrBaseModel | ModelDump) -> str:
    if isinstance(data, TrBaseModel):
        return re.split(r"[@:]", get_model_id(data))[0]
    return data["tr_annotation"]["model_name"]


def get_model_created_by(data: TrBaseModel | ModelDump) -> str:
    """모델을 만든 프로세스의 인스턴스 ID."""
    if isinstance(data, TrBaseModel):
        # uid는 `클래스@모듈:인스턴스ID:순번`이다. 인스턴스 ID에 `@`·`:`가 들어 있으므로
        # 쪼개지 않고 앞의 `클래스@모듈:`과 뒤의 `:순번`을 떼어 낸다.
        prefix = f"{get_model_name(data)}@{get_module_name(data)}:"
        return get_model_uid(data).removeprefix(prefix).rsplit(":", 1)[0]
    return data["tr_annotation"]["created_by"]


class Runnable[Tin: DataModel, Tout: DataModel](Protocol):
    async def invoke(self, input: Tin) -> Tout | None: ...


class Pipeline[Treq: BaseRequest]:
    """상위 요청의 심볼 하나에서 시작해 단계(`Runnable`)를 차례로 거치는 파이프라인.

    `req(symbol) | step | ...`으로 만든다. `upstream_symbol`은 상위 표기(원천이 아는 심볼)다.
    """

    def __init__(self, pre: Pipeline[Treq], *steps: Runnable):
        self._upstream = pre.upstream
        self._upstream_symbol = pre.upstream_symbol
        self._steps = steps

    def __or__(self, other: Runnable) -> Pipeline[Treq]:
        return Pipeline(self, *self._steps, other)

    @property
    def upstream(self) -> Treq:
        return self._upstream

    @property
    def upstream_symbol(self) -> str:
        return self._upstream_symbol

    async def invoke(self, input: DataModel) -> DataModel | None:
        data = input
        for step in self._steps:
            data = await step.invoke(data)
            if not data:
                return
        return data


class PipelineHead[Treq: BaseRequest](Pipeline):
    """단계가 아직 없는 파이프라인의 시작점. `req(symbol)`이 만든다."""

    def __init__(self, upstream: Treq, upstream_symbol: str):
        self._upstream = upstream
        self._upstream_symbol = upstream_symbol
        self._steps = ()


class BaseRequest(TrBaseModel):
    _tr_model_type: ClassVar[ModelType] = "unregistered"

    def __call__(self, symbol: str) -> Pipeline[Self]:
        return PipelineHead(self, symbol)


class SourceRequest(BaseRequest):
    """원천 요청. content_id가 같은 요청끼리 스테이지를 공유한다."""


class DerivedRequest(BaseRequest):
    """상위 요청(`require`)의 데이터를 받아 변환하는 파생 요청.

    content_id가 같은 요청끼리 스테이지를 공유한다.
    """

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
        ) -> tuple[SourceRequest | DerivedRequest, set[str]]:
            return plain(req), symbols

        cls._tr_require_cb = with_sym

    @property
    def tr_upstream(self) -> SourceRequest | DerivedRequest:
        """상위 요청."""
        callback = type(self)._tr_require_cb
        if callback is None:
            raise ModelError(f"'require' 정의가 필요하다. - {get_model_id(self)}")
        return callback(self, set[str]())[0]

    def resolve_upstream(
        self, symbols: set[str]
    ) -> tuple[SourceRequest | DerivedRequest, set[str]]:
        """상위 요청과, 하위 심볼 집합을 상위 표기로 바꾼 심볼 집합을 돌려준다."""
        callback = type(self)._tr_require_cb
        if callback is None:
            raise ModelError(f"'require' 정의가 필요하다. - {get_model_id(self)}")
        return callback(self, set(symbols))

    @overload
    @classmethod
    def require[Treq: SourceRequest | DerivedRequest](
        cls, cb: Callable[[Self], Treq]
    ) -> Callable[[Self], Treq]: ...

    @overload
    @classmethod
    def require[Treq: SourceRequest | DerivedRequest](
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


type RequireCb[Tdep: DerivedRequest] = Callable[[Tdep], SourceRequest | DerivedRequest]
type RequireCbWithSym[Tdep: DerivedRequest] = Callable[
    [Tdep, set[str]], tuple[SourceRequest | DerivedRequest, set[str]]
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


class SessionRequest(BaseRequest):
    """심볼마다 파이프라인을 붙여 상위 데이터를 분석하는 세션 요청.

    상태를 가지므로 content_id가 같아도 스테이지를 공유하지 않는다. 요청할 때마다
    컨텍스트와 스테이지가 새로 생긴다.
    """


class DataModel(TrBaseModel):
    _tr_model_type: ClassVar[ModelType] = "data"
    symbol: str = ""
    _tr_req_content_id: str = ""

    def get_tr_req_content_id(self) -> str:
        return self._tr_req_content_id


def is_source(req: BaseRequest) -> bool:
    return isinstance(req, SourceRequest) and get_model_type(req) == "source"


def is_derived(req: BaseRequest) -> bool:
    return isinstance(req, DerivedRequest) and get_model_type(req) == "derived"


def is_session(req: BaseRequest) -> bool:
    return isinstance(req, SessionRequest) and get_model_type(req) == "session"


def parse_dump(json_data: str | bytes | Mapping[str, Any]) -> ModelDump:
    try:
        raw: Any = dict(json_data) if isinstance(json_data, Mapping) else json.loads(json_data)
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ModelValidationError()
        raw["tr_annotation"] = _tr_annotation_adapter.validate_python(raw.get("tr_annotation"))
        return cast(ModelDump, raw)
    except Exception as e:
        raise ModelValidationError("parse_dump() 유효성 검사 실패") from e


@overload
def load_model(data: str | bytes | ModelDump, target: None = None) -> TrBaseModel: ...
@overload
def load_model(data: str | bytes | ModelDump, target: ModuleType) -> TrBaseModel: ...
@overload
def load_model[T: TrBaseModel](data: str | bytes | ModelDump, target: type[T]) -> T: ...


def load_model[T: TrBaseModel](
    data: str | bytes | ModelDump, target: type[T] | ModuleType | None = None
) -> T | TrBaseModel:
    """직렬화된 모델을 되살린다.

    `target`이 클래스면 그 클래스로, 모듈이면 그 모듈에서, 없으면 어노테이션의 모듈명으로
    클래스를 찾는다.
    """
    try:
        dump = parse_dump(data)
        annotation = dump["tr_annotation"]

        if isinstance(target, type):
            model_type = target
        else:
            module = target or import_module(annotation["module_name"])
            candidate = getattr(module, annotation["model_name"], None)
            if not isinstance(candidate, type) or not issubclass(candidate, TrBaseModel):
                raise ModelValidationError(
                    f"유효한 모델 클래스를 찾을 수 없습니다: "
                    f"{module.__name__}.{annotation['model_name']}"
                )
            model_type = candidate

        return model_type.model_validate(dump)
    except ModelValidationError:
        raise
    except Exception as e:
        raise ModelValidationError("load_model() 유효성 검사 실패") from e


def cast_model[T: TrBaseModel](data: TrBaseModel, target_type: type[T]) -> T:
    """모델 인스턴스를 복사하지 않고 검증한 타입으로 좁힌다."""
    if not isinstance(data, TrBaseModel):
        raise ModelValidationError("data가 TrBaseModel 인스턴스가 아닙니다")
    if not isinstance(target_type, type) or not issubclass(target_type, TrBaseModel):
        raise ModelValidationError("target_type이 TrBaseModel 하위 클래스가 아닙니다")
    data_model_id = get_model_id(data)
    target_model_id = get_model_id(target_type)
    if data_model_id != target_model_id:
        raise ModelValidationError(
            f"모델 ID가 일치하지 않습니다: {data_model_id} != {target_model_id}"
        )
    return cast(T, data)


# 받는 쪽이 닫혔다면 `ChannelClosed` 예외를 발생해야 한다.
type Sender[T] = Callable[[T], Coroutine[Any, Any, None]]


type Receiver[T] = Callable[[], Coroutine[Any, Any, T]]
