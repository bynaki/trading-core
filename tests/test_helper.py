"""`helper.py` 명세 — digest/id 생성과 이름 기반 `TaskManager`."""

from asyncio import CancelledError, Event, create_task, sleep
from collections.abc import AsyncIterator, Coroutine
from typing import Any

import pytest

from trading_core.helper import (
    TaskManager,
    TaskManagerError,
    generate_digest,
    generate_id,
    verify_module,
)

from .support.harness import wait_until


@pytest.fixture
async def manager() -> AsyncIterator[TaskManager]:
    """테스트마다 새 `TaskManager`를 주고, 끝나면 남은 태스크를 정리한다."""

    tmg = TaskManager("test")
    try:
        yield tmg
    finally:
        await tmg.stop()


class Signal:
    """태스크가 실제로 실행·취소되었는지 알려 주는 관찰용 코루틴 묶음."""

    def __init__(self) -> None:
        self.started = Event()
        self.cancelled = Event()
        self.finished = Event()

    async def forever(self) -> None:
        """취소될 때까지 끝나지 않는 태스크."""

        self.started.set()
        try:
            await Event().wait()
        except CancelledError:
            self.cancelled.set()
            raise

    async def once(self) -> None:
        """한 번 실행되고 곧바로 끝나는 태스크."""

        self.started.set()
        self.finished.set()

    async def fail(self) -> None:
        """예외를 던지는 태스크."""

        self.started.set()
        raise RuntimeError("의도된 실패")


def _discard(coro: Coroutine[Any, Any, None]) -> None:
    """제출에 실패한 코루틴을 닫는다(never-awaited 경고 방지)."""

    coro.close()


# ===== digest / id =====


def test_generate_digest_is_deterministic():
    """같은 입력은 항상 같은 digest를, 다른 입력은 다른 digest를 낸다."""

    assert generate_digest("a") == generate_digest("a")
    assert generate_digest("a") != generate_digest("b")
    assert len(generate_digest("a")) == 16
    assert len(generate_digest("a", 8)) == 8


def test_generate_id_is_random_with_requested_length():
    """`generate_id()`는 요청한 길이의 서로 다른 값을 낸다."""

    assert len(generate_id()) == 16
    assert len(generate_id(8)) == 8
    assert generate_id() != generate_id()


def test_verify_module_returns_defining_module():
    """`verify_module()`은 객체가 정의된 모듈을 돌려준다."""

    assert verify_module(TaskManager).__name__ == "trading_core.helper"


# ===== 제출 =====


async def test_submit_runs_task(manager: TaskManager):
    """제출한 코루틴은 supervisor가 실행한다."""

    signal = Signal()
    await manager.start()
    await manager.submit(signal.once(), "once")
    await wait_until(signal.finished.is_set, "태스크가 실행되지 않았다.")


async def test_submit_rejects_empty_name(manager: TaskManager):
    """이름 없는 태스크는 제출할 수 없다."""

    signal = Signal()
    coro = signal.once()
    with pytest.raises(TaskManagerError):
        await manager.submit(coro, "")
    _discard(coro)


async def test_submit_rejects_duplicate_name(manager: TaskManager):
    """이름은 실행 중인 태스크의 정체성이라 중복될 수 없다."""

    first, second = Signal(), Signal()
    await manager.start()
    await manager.submit(first.forever(), "dup")
    await wait_until(first.started.is_set, "첫 태스크가 시작되지 않았다.")

    coro = second.forever()
    with pytest.raises(TaskManagerError):
        await manager.submit(coro, "dup")
    _discard(coro)


async def test_pending_name_is_also_occupied(manager: TaskManager):
    """큐에서 대기 중인 이름도 점유된 것으로 본다(supervisor 미시작 상태)."""

    first, second = Signal(), Signal()
    pending = first.forever()
    await manager.submit(pending, "pending")  # 아직 실행되지 않는다
    coro = second.forever()
    with pytest.raises(TaskManagerError):
        await manager.submit(coro, "pending")
    _discard(coro)
    _discard(pending)  # supervisor를 시작하지 않았으므로 직접 닫는다


# ===== 이름 기반 취소 =====


async def test_cancel_by_name_cancels_running_task(manager: TaskManager):
    """실행 중인 태스크는 이름으로 취소된다."""

    signal = Signal()
    await manager.start()
    await manager.submit(signal.forever(), "running")
    await wait_until(signal.started.is_set, "태스크가 시작되지 않았다.")

    assert await manager.cancel_by_name("running") is True
    assert signal.cancelled.is_set()


async def test_cancel_by_name_releases_the_name(manager: TaskManager):
    """취소는 이름 점유가 풀릴 때까지 기다리므로 같은 이름을 곧바로 재사용할 수 있다.

    `Domain`이 심볼 합집합 변경으로 generator를 재시작할 때 기대는 성질이다.
    """

    first, second = Signal(), Signal()
    await manager.start()
    await manager.submit(first.forever(), "restart")
    await wait_until(first.started.is_set, "첫 태스크가 시작되지 않았다.")

    await manager.cancel_by_name("restart")
    await manager.submit(second.forever(), "restart")  # 이름 충돌이 나면 안 된다
    await wait_until(second.started.is_set, "재제출한 태스크가 시작되지 않았다.")


async def test_cancel_by_name_on_unknown_name(manager: TaskManager):
    """없는 이름을 취소하면 `False`."""

    await manager.start()
    assert await manager.cancel_by_name("없는-이름") is False


async def test_cancel_by_name_skips_pending_task(manager: TaskManager):
    """실행 전에 취소하면 코루틴이 아예 실행되지 않는다."""

    signal = Signal()
    await manager.submit(signal.forever(), "pending")  # supervisor가 아직 없다
    cancelling = create_task(manager.cancel_by_name("pending"))
    await sleep(0)  # 취소 예약이 등록되도록 한 번 양보한다

    await manager.start()
    assert await cancelling is True
    assert not signal.started.is_set()
    await manager.submit(signal.once(), "pending")  # 이름이 풀렸다
    await wait_until(signal.finished.is_set, "재제출한 태스크가 실행되지 않았다.")


# ===== 종료 · 실패 =====


async def test_stop_cancels_running_tasks(manager: TaskManager):
    """`stop()`은 supervisor와 하위 태스크를 모두 정리한다."""

    signal = Signal()
    await manager.start()
    await manager.submit(signal.forever(), "running")
    await wait_until(signal.started.is_set, "태스크가 시작되지 않았다.")

    await manager.stop()
    assert signal.cancelled.is_set()
    assert await manager.cancel_by_name("running") is False


async def test_task_failure_callback_receives_exception(manager: TaskManager):
    """태스크가 예외로 끝나면 실패 콜백이 이름과 함께 호출된다."""

    signal = Signal()
    failures: list[tuple[Exception, str]] = []

    async def on_failure(exc: Exception, name: str) -> None:
        failures.append((exc, name))

    manager.on_task_failure(on_failure)
    await manager.start()
    await manager.submit(signal.fail(), "failing")
    await wait_until(lambda: bool(failures), "실패 콜백이 호출되지 않았다.")

    exc, name = failures[0]
    assert isinstance(exc, RuntimeError)
    assert name == "failing"


async def test_failed_task_releases_its_name(manager: TaskManager):
    """예외로 끝난 태스크의 이름도 해제된다."""

    first, second = Signal(), Signal()
    await manager.start()
    await manager.submit(first.fail(), "reused")
    await wait_until(first.started.is_set, "첫 태스크가 시작되지 않았다.")
    await wait_until(lambda: manager.submit_count == 0, "실패한 태스크가 정리되지 않았다.")
    await manager.submit(second.once(), "reused")
    await wait_until(second.finished.is_set, "재제출한 태스크가 실행되지 않았다.")
