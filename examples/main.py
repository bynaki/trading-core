from asyncio import Task, create_task, gather, run
from typing import Any

import ex01
import ex02

from trading_core import (
    Domain,
)


async def main():
    domain = Domain()
    await domain.start()
    tasks: set[Task[Any]] = set()
    tasks.add(create_task(ex01.run_ex(domain)))
    tasks.add(create_task(ex02.run_ex(domain)))
    await gather(*tasks)


if __name__ == "__main__":
    run(main())
