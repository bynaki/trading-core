"""서로 다른 이름 요청이 원천 스테이지를 공유하는 실행 예제."""

from asyncio import TaskGroup, run, sleep
from typing import Literal

from trading_core import Domain

if __package__:
    from .refer import NamingReq
else:
    from refer import NamingReq


async def run_ex(domain: Domain) -> None:
    """종류와 심볼 집합이 다른 요청을 시간차로 동시에 구독한다."""

    print("===== runing ex02 =====")
    symbols01 = {"SYMBOL_A", "SYMBOL_B", "SYMBOL_C", "SYMBOL_D", "SYMBOL_E"}
    symbols02 = {"SYMBOL_A", "SYMBOL_B", "SYMBOL_C"}
    symbols03 = {"SYMBOL_C", "SYMBOL_D", "SYMBOL_E"}

    async def request(kind: Literal["flower", "dog", "cat"], symbols: set[str], count: int) -> None:
        """지정한 개수만 소비한 뒤 구독을 닫아 공유 심볼을 갱신한다."""

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
        tg.create_task(request("dog", symbols03, 1))
        await sleep(0.5)
        tg.create_task(request("flower", symbols02, 10))
        await sleep(0.5)
        tg.create_task(request("cat", symbols01, 5))
        await sleep(0.5)
        tg.create_task(request("flower", symbols03, 3))
        await sleep(0.5)
        tg.create_task(request("cat", symbols02, 3))
        await sleep(0.5)
        tg.create_task(request("dog", symbols02, 7))
    print("===== finished ex02 =====")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex02를 실행한다."""

    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    run(main())
