import json
import re
from collections.abc import Callable
from typing import (
    Any,
    ClassVar,
    Protocol,
    Self,
    TypedDict,
)

from pydantic import BaseModel, PrivateAttr, computed_field
from pydantic.main import IncEx

from .helper import generate_digest, generate_id, verify_module


class ModelError(Exception): ...


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


class TrBaseModel(BaseModel):
    _tr_model_id: ClassVar[str] = "__none__"  # 클래스 정의 시 자동 생성됨
    _tr_model_type: ClassVar[str] = "base"
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


# ===== Helper Functions =====


def get_model_inst_id(data: TrBaseModel | DataDump) -> str:
    if isinstance(data, TrBaseModel):
        return data._tr_id  # type: ignore
    return data["tr_annotation"]["id"]


def get_model_type(data: TrBaseModel | type[TrBaseModel] | DataDump) -> str:
    if isinstance(data, dict):
        return data["tr_annotation"]["model_type"]
    return data._tr_model_type  # type: ignore


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


class Runnable(Protocol):
    async def invoke(self, input: DataModel) -> DataModel | None: ...


class Sequence[Treq: RequestModel]:
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


class RequireSequence[Treq: RequestModel](Sequence):
    def __init__(self, require: Treq, symbol: str):
        self._req = require
        self._symbol = symbol
        self._steps = ()
        # self._joins: set[Sequence[RequestModel]] = set()


class RequestModel(TrBaseModel):
    _tr_model_type: ClassVar[str] = "unregistered"
    # _tr_request_list: ClassVar[list[Callable[[Self], RequestModel]]] = []

    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        cls._tr_require_cb: tuple[str, Callable[[Self], RequestModel]] | None = None

    @classmethod
    def require[Treq: RequestModel](cls, t_model: type[Treq]):
        def wraper(cb: Callable[[Self], Treq]):
            cls._tr_require_cb = (t_model._tr_model_id, cb)

        return wraper

    @property
    def tr_require(self) -> RequestModel | None:
        if not self._tr_require_cb:
            return None
        return self._tr_require_cb[1](self)

    def __call__(self, symbol: str) -> Sequence[Self]:
        return RequireSequence(self, symbol)


class DataModel(TrBaseModel):
    _tr_model_type: ClassVar[str] = "data"
    symbol: str = ""


# close 되었다면 ClosedConnection 예외를 발생해야 한다.
# type Sender = Callable[[DataModel], Coroutine[Any, Any, None]]
class Sender(Protocol):
    async def __call__(self, data: DataModel) -> None: ...
    async def close(self) -> None: ...


# type Receiver = Callable[[], Coroutine[Any, Any, DataModel]]
class Receiver(Protocol):
    async def __call__(self) -> DataModel: ...


#     async def close(self) -> None: ...
