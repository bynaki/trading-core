"""비동기 스트림을 관찰하기 위한 테스트 도구."""

from asyncio import sleep, timeout
from collections.abc import Callable

from trading_core import DataModel

POLL_INTERVAL = 0.005
"""`wait_until()`이 조건을 다시 확인하는 간격."""

DEFAULT_TIMEOUT = 2.0
"""조건 대기의 기본 제한 시간. 발행 간격(0.01초)에 비하면 넉넉하다."""


async def wait_until(
    predicate: Callable[[], bool],
    message: str = "",
    timeout_sec: float = DEFAULT_TIMEOUT,
) -> None:
    """`predicate`가 참이 될 때까지 기다린다. 제한 시간을 넘기면 `AssertionError`."""

    try:
        async with timeout(timeout_sec):
            while not predicate():
                await sleep(POLL_INTERVAL)
    except TimeoutError as e:
        raise AssertionError(message or f"{timeout_sec}초 안에 조건이 충족되지 않았다.") from e


class Recorder:
    """받은 데이터를 모아 두는 `Sender` 구현."""

    def __init__(self, tag: str = "") -> None:
        self.tag = tag
        self.received: list[DataModel] = []

    async def __call__(self, data: DataModel) -> None:
        self.received.append(data)

    @property
    def count(self) -> int:
        """지금까지 받은 데이터 개수."""

        return len(self.received)

    @property
    def symbols(self) -> set[str]:
        """지금까지 받은 데이터의 심볼 집합."""

        return {data.symbol for data in self.received}

    def clear(self) -> None:
        """기록을 비운다. 특정 구간의 수신만 보고 싶을 때 쓴다."""

        self.received.clear()

    async def wait_for(self, count: int, timeout_sec: float = DEFAULT_TIMEOUT) -> None:
        """누적 수신이 `count`건이 될 때까지 기다린다."""

        await wait_until(
            lambda: self.count >= count,
            f"'{self.tag}'가 {count}건을 받지 못했다. (현재 {self.count}건)",
            timeout_sec,
        )
