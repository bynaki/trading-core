class ModelError(Exception): ...


class ModelValidationError(Exception): ...


class BindError(Exception): ...


class DomainError(Exception): ...


class ChannelClosed(Exception): ...


class StageFailed(Exception):
    """스테이지나 세션 슬롯이 실패해 `symbols`의 구독이 끊겼다.

    코어는 재시도하지 않는다. 실패한 심볼은 구독에서 빠지고, 소비자는 `update()`로 다시
    넣을 수 있다(새 스테이지가 `init` 콜백부터 다시 만들어진다). 원인은 `cause`에 문자열로
    요약해 두어 프로세스 밖으로도 옮길 수 있다. 같은 프로세스 안에서는 `__cause__`가 원래
    예외(상위가 실패해 연쇄되었으면 상위의 `StageFailed`)를 가리킨다.

    binder가 `SymbolRejected`로 심볼 몇 개만 거부했으면 스테이지는 남은 심볼로 계속 돌고,
    `symbols`에는 거부된 심볼만 든다.
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


class SymbolRejected(Exception):
    """원천·파생 binder가 `symbols`를 줄 수 없다고 알릴 때 generator에서 던진다.

    상장 폐지나 없는 심볼처럼 심볼 하나 때문에 스테이지 전체를 내리지 않으려고 쓴다. 코어는 그
    심볼만 구독에서 빼 구독한 소비자에게 알리고, 남은 심볼로 generator를 다시 띄운다. 다른 예외는
    지금처럼 스테이지 전체의 실패다. 지금 구독되지 않은 심볼만 들었으면 스테이지 전체의 실패로
    본다(같은 합집합으로 다시 띄우면 끝없이 되풀이되므로).
    """

    def __init__(self, symbols: str | set[str] | frozenset[str], reason: str = "") -> None:
        self.symbols = frozenset({symbols} if isinstance(symbols, str) else symbols)
        self.reason = reason
        super().__init__(f"심볼을 줄 수 없다. - {sorted(self.symbols)}: {reason}")


class TaskManagerError(Exception): ...


class LogConfigError(Exception): ...
