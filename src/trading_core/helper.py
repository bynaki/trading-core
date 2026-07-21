import contextlib
import hashlib
import inspect
import os
from asyncio import (
    CancelledError,
    Event,
    Queue,
    Task,
    create_task,
    current_task,
    gather,
)
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any


def verify_module(obj: object, _filename: str | None = None):
    module = inspect.getmodule(obj, _filename)
    if module is None:
        raise ValueError(f"'{obj}'은 모듈에 속해있어야 한다.")
    return module


def generate_id(length: int = 16) -> str:
    # os.urandom()으로 안전한 난수 생성
    random_bytes = os.urandom(32)
    # sha256 해시 적용
    sha256_hash = hashlib.sha256(random_bytes).hexdigest()
    # 원하는 길이만큼 잘라서 반환
    return sha256_hash[:length]


def generate_digest(content: str, length: int = 16):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:length]


class TaskManagerError(Exception): ...


class TaskManager:
    def __init__(self, id: str = ""):
        self._id = id or generate_id()
        self._queue = Queue[tuple[Coroutine[Any, Any, None], str]]()
        self._tasks: dict[str, Task[None]] = {}  # 이름 -> 실행 중 태스크
        self._names: set[str] = set()  # 예약된(대기 + 실행) 이름 전체
        self._release_events: dict[str, Event] = {}
        self._cancelled_pending: set[str] = set()  # 실행 전 취소된 대기 태스크 이름
        self._running = False
        self._supervisor: Task[None] | None = None
        self._task_failure_cb: Callable[[Exception, str], Awaitable[None]] | None = None
        self._stopping = False
        self._submit_count = 0

    async def start(self):
        if self._running:
            return
        self._running = True
        self._supervisor = create_task(self._run())

    async def wait(self):
        if self._supervisor:
            await self._supervisor

    async def stop(self):
        if not self._running or self._stopping:
            return
        self._stopping = True
        self._running = False
        curr = current_task()  # 현재 리소스를 정리 중인 태스크 확인
        # supervisor 종료 시도
        if self._supervisor and self._supervisor != curr:  # 자신이 supervisor가 아닐 때만
            self._supervisor.cancel()
            with contextlib.suppress(CancelledError):
                await self._supervisor
        await self._cancel_all()  # 나머지 하위 태스크들 종료
        self._stopping = False

    async def cancel_by_name(self, name: str) -> bool:
        """이름으로 태스크를 찾아 취소하고 이름 점유가 해제될 때까지 기다린다."""
        released = self._release_events.get(name)
        task = self._tasks.get(name)
        if task is not None:  # 실행 중
            if task is current_task():  # 자기 자신이면 취소 안 함
                return False
            task.cancel()
            # _task_wrapper가 CancelledError를 다시 raise하므로 gather로 취소 완료까지 대기
            await gather(task, return_exceptions=True)
            if released:
                await released.wait()
            return True
        if name in self._names:  # 아직 큐 대기 중 -> 실행 시점에 취소되도록 예약
            self._cancelled_pending.add(name)
            if released:
                await released.wait()
            return True
        return False  # 그런 이름 없음

    async def submit(self, coro: Coroutine[Any, Any, None], name: str):
        if not name:
            raise TaskManagerError("태스크 이름은 비어 있을 수 없다.")
        if name in self._names:
            raise TaskManagerError(f"이미 사용 중인 태스크 이름이다. - '{name}'")
        self._names.add(name)  # 대기 중에도 이름을 점유한다
        self._release_events[name] = Event()
        self._submit_count += 1
        print("-" * 80)
        print(f"[TASK SUBMIT({self._submit_count})] - id: {self._id}")
        print(f"name: {name}")
        await self._queue.put((coro, name))

    @property
    def id(self):
        return self._id

    @property
    def submit_count(self):
        return self._submit_count

    async def _run(self):
        try:
            while self._running:
                coro, name = await self._queue.get()
                if name in self._cancelled_pending:  # 실행 전에 취소됨
                    self._skip_pending(coro, name)
                    continue
                task = create_task(self._task_wrapper(coro, name), name=name)
                self._tasks[name] = task
                task.add_done_callback(lambda _t, c=coro, n=name: self._release(n, c))
        except CancelledError:
            # print("CanceledError")
            ...

    async def _task_wrapper(self, coro: Coroutine[Any, Any, None], name: str):
        try:
            await coro
            self.on_task_finished(name)
        except CancelledError:
            self.on_task_cancelled(name)
            raise
        except Exception as e:
            self.on_task_exception(e, name)
            if self._task_failure_cb:
                await self._task_failure_cb(e, name)
        finally:
            self._submit_count -= 1

    def _release(self, name: str, coro: Coroutine[Any, Any, None] | None = None):
        """완료된 태스크의 이름 점유를 해제한다."""
        if coro is not None:
            coro.close()
        self._tasks.pop(name, None)
        self._names.discard(name)
        if released := self._release_events.pop(name, None):
            released.set()

    def _skip_pending(self, coro: Coroutine[Any, Any, None], name: str):
        """실행 전에 취소된 대기 태스크를 정리한다."""
        self._cancelled_pending.discard(name)
        coro.close()  # 시작 전 coro 정리 (never-awaited 경고 방지)
        self._submit_count -= 1  # _task_wrapper를 거치지 않으므로 직접 차감
        self.on_task_cancelled(name)
        self._release(name)

    async def _cancel_all(self):
        curr = current_task()
        tasks = [t for t in self._tasks.values() if t is not curr]
        for t in tasks:
            t.cancel()
        if tasks:
            await gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._names.clear()
        self._cancelled_pending.clear()
        for released in self._release_events.values():
            released.set()
        self._release_events.clear()
        # if curr:
        #     curr.cancel()
        #     await curr

    # ======= hooks =======

    def on_task_exception(self, exc: Exception, name: str):
        print("-" * 80)
        print(f"[TASK ERROR({self._submit_count})] {exc!r} - id: {self._id}")
        print(f"name: {name}")

    def on_task_finished(self, name: str):
        print("-" * 80)
        print(f"[TASK FINISHED({self._submit_count})] - id: {self._id}")
        print(f"name: {name}")

    def on_task_cancelled(self, name: str):
        print("-" * 80)
        print(f"[TASK CANCELLED({self._submit_count})] - id: {self._id}")
        print(f"name: {name}")

    # async def on_task_failure(self):
    #     """failure hook (override)"""
    def on_task_failure(self, cb: Callable[[Exception, str], Awaitable[None]]):
        self._task_failure_cb = cb
