from asyncio import Task, create_task, gather, run
from typing import Any

import ex01
import ex02

from trading_core import (
    Domain,
)


async def run_ex01(domain: Domain):
    req01 = ex01.CountReq(start=0)
    async with domain.request(req01, {"BTC", "USDT", "ETH", "XRP"}) as gen:
        async for data in gen:
            print(data.model_dump_json(indent=2))


async def run_ex02(domain: Domain):
    req02 = ex02.NamingAllReq(count=10)
    async with domain.request(req02, {"BTC", "USDT", "ETH", "XRP"}) as gen:
        async for data in gen:
            print(data.model_dump_json(indent=2))


async def main():
    domain = Domain()
    await domain.start()
    tasks: set[Task[Any]] = set()
    tasks.add(create_task(run_ex01(domain)))
    tasks.add(create_task(run_ex02(domain)))
    await gather(*tasks)


if __name__ == "__main__":
    run(main())
