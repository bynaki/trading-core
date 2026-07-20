from asyncio import Task, TaskGroup, create_task, gather, run
from typing import Any, Literal

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
    symbols = {"SYMBOL_A", "SYMBOL_B", "SYMBOL_C", "SYMBOL_D", "SYMBOL_E"}

    async def request(kind: Literal["flower", "dog", "cat"]):
        req_flower = ex02.NamingReq(kind=kind, count=10)
        async with domain.request(req_flower, symbols) as gen:
            async for data in gen:
                print(data.model_dump_json(indent=2))

    async with TaskGroup() as tg:
        tg.create_task(request("flower"))
        tg.create_task(request("dog"))
        tg.create_task(request("cat"))


async def main():
    domain = Domain()
    await domain.start()
    tasks: set[Task[Any]] = set()
    tasks.add(create_task(run_ex01(domain)))
    tasks.add(create_task(run_ex02(domain)))
    await gather(*tasks)


if __name__ == "__main__":
    run(main())
