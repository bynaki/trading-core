"""서로 다른 이름 요청이 원천 스테이지를 공유하는 실행 예제."""

from asyncio import TaskGroup, run, sleep
from pathlib import Path
from typing import Literal

from trading_core import Domain, cast_model
from trading_core.logger import configure, get_logger

if __package__:
    from .refer import NamingData, NamingReq
else:
    from refer import NamingData, NamingReq

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex02")


async def run_ex(domain: Domain) -> None:
    """종류와 심볼 집합이 다른 요청을 시간차로 동시에 구독한다."""

    log.info("━━━━━━━━━━ 시작: 파생 요청 여럿이 원천 하나를 공유하기 ━━━━━━━━━━")
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
                d = cast_model(data, NamingData)
                i += 1
                log.info(f"수신 {kind}", symbol=d.symbol, name=d.name, n=f"{i}/{count}")

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
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex02를 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    run(main())
