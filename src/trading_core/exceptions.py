class ModelError(Exception): ...


class ModelValidationError(Exception): ...


class BindError(Exception): ...


class StageError(Exception): ...


class DomainError(Exception): ...


class ChannelClosed(Exception): ...


class StageFailed(Exception):
    """스테이지나 세션 슬롯이 실패해 `symbols`의 구독이 끊겼다.

    코어는 재시도하지 않는다. 실패한 심볼은 구독에서 빠지고, 소비자는 `update()`로 다시
    넣을 수 있다(새 스테이지가 `init` 콜백부터 다시 만들어진다). 원인은 `cause`에 문자열로
    요약해 두어 프로세스 밖으로도 옮길 수 있다. 같은 프로세스 안에서는 `__cause__`가 원래
    예외(상위가 실패해 연쇄되었으면 상위의 `StageFailed`)를 가리킨다.
    """

    def __init__(self, content_id: str, symbols: set[str] | frozenset[str], cause: str) -> None:
        self.content_id = content_id
        self.symbols = frozenset(symbols)
        self.cause = cause
        super().__init__(f"스테이지가 실패했다. - {content_id} {sorted(self.symbols)}: {cause}")

    @classmethod
    def from_exception(
        cls, content_id: str, symbols: set[str] | frozenset[str], exc: BaseException
    ) -> StageFailed:
        """`exc`를 원인으로 하는 `StageFailed`를 만든다. `__cause__`도 잇는다."""

        failed = cls(content_id, symbols, f"{type(exc).__name__}: {exc}")
        failed.__cause__ = exc
        return failed


class TaskManagerError(Exception): ...


class LogConfigError(Exception): ...
