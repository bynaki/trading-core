"""모든 예제를 하나의 `Domain`에서 동시에 실행한다."""

from asyncio import Task, create_task, gather, run
from typing import Any

from ex01.run_ex import run_ex as run_ex01
from ex02.run_ex import run_ex as run_ex02
from ex03.run_ex import run_ex as run_ex03

from trading_core import (
    Domain,
)


async def main() -> None:
    """공유 `Domain`을 시작하고 각 예제 실행 태스크가 끝날 때까지 기다린다."""

    domain = Domain()
    await domain.start()
    tasks: set[Task[Any]] = set()
    tasks.add(create_task(run_ex01(domain)))
    tasks.add(create_task(run_ex02(domain)))
    tasks.add(create_task(run_ex03(domain)))
    try:
        await gather(*tasks)
    finally:
        await domain.stop()


if __name__ == "__main__":
    run(main())
