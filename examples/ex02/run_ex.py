from asyncio import TaskGroup, run, sleep
from typing import Literal

from trading_core import Domain

if __package__:
    from .refer import NamingReq
else:
    from refer import NamingReq


async def run_ex(domain: Domain):
    print("===== runing ex02 =====")
    symbols01 = {"SYMBOL_A", "SYMBOL_B", "SYMBOL_C", "SYMBOL_D", "SYMBOL_E"}
    symbols02 = {"SYMBOL_A", "SYMBOL_B", "SYMBOL_C"}
    symbols03 = {"SYMBOL_C", "SYMBOL_D", "SYMBOL_E"}

    async def request(kind: Literal["flower", "dog", "cat"], symbols: set[str], count: int):
        req = NamingReq(kind=kind)
        i = 0
        async with domain.request(req, symbols) as gen:
            async for data in gen:
                if i >= count:
                    break
                print(data.model_dump_json(indent=2))
                i += 1
                print(f"{i} / {count} ---------------------------")

    async with TaskGroup() as tg:
        tg.create_task(request("flower", symbols02, 10))
        await sleep(1)
        tg.create_task(request("dog", symbols03, 5))
        await sleep(1)
        tg.create_task(request("cat", symbols01, 3))
        await sleep(1)
        tg.create_task(request("flower", symbols03, 10))
        await sleep(1)
        tg.create_task(request("dog", symbols02, 10))
        await sleep(1)
        tg.create_task(request("cat", symbols02, 1))
    print("===== finished ex02 =====")


async def main():
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    run(main())
