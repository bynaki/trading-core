"""단일 Domain에서 독립 예제와 의존 요청 예제를 동시에 실행한다."""

from asyncio import Task, TaskGroup, create_task, gather, run, sleep
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
    symbols01 = {"SYMBOL_A", "SYMBOL_B", "SYMBOL_C", "SYMBOL_D", "SYMBOL_E"}
    symbols02 = {"SYMBOL_A", "SYMBOL_B", "SYMBOL_C"}
    symbols03 = {"SYMBOL_C", "SYMBOL_D", "SYMBOL_E"}

    async def request(kind: Literal["flower", "dog", "cat"], symbols: set[str]):
        req = ex02.NamingReq(kind=kind, count=10)
        async with domain.request(req, symbols) as gen:
            async for data in gen:
                print(data.model_dump_json(indent=2))

    async with TaskGroup() as tg:
        tg.create_task(request("flower", symbols02))
        await sleep(1)
        tg.create_task(request("dog", symbols03))
        await sleep(1)
        tg.create_task(request("cat", symbols01))
        await sleep(1)
        tg.create_task(request("flower", symbols03))
        await sleep(1)
        tg.create_task(request("dog", symbols02))
        await sleep(1)
        tg.create_task(request("cat", symbols02))


async def main():
    domain = Domain()
    await domain.start()
    tasks: set[Task[Any]] = set()
    tasks.add(create_task(run_ex01(domain)))
    tasks.add(create_task(run_ex02(domain)))
    await gather(*tasks)


if __name__ == "__main__":
    run(main())
