from typing import ClassVar, overload


class BaseTest: ...


class Test(BaseTest): ...


class TestFetchable(BaseTest):
    def __init__(self) -> None:
        self.require: bool = False

    def set_require(self, req: bool):
        self.require = req


class BaseBinder:
    def __init__(self, name: str) -> None:
        self.name = name


class Binder(BaseBinder):
    def __init__(self) -> None:
        super().__init__("binder")


class FetchableBinder(BaseBinder):
    def __init__(self) -> None:
        super().__init__("fetchable_binder")


@overload
def require[T: Test](test_t: type[T]) -> Binder: ...
@overload
def require[T: TestFetchable](test_t: type[T]) -> FetchableBinder: ...


def require[T: Test | TestFetchable](test_t: type[T]) -> Binder | FetchableBinder:
    if issubclass(test_t, TestFetchable):
        return FetchableBinder()
    else:
        return Binder()


print(require(Test).name)
print(require(TestFetchable).name)


class BaseModel:
    tr_model_type: ClassVar[str] = "base"


class RequestModel(BaseModel): ...


class DataModel(BaseModel): ...


RequestModel.tr_model_type = "request"
DataModel.tr_model_type = "data"


print(BaseModel.tr_model_type)
print(RequestModel.tr_model_type)
print(DataModel.tr_model_type)
