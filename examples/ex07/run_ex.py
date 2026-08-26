"""ex07 스윙 스트림을 실제 `Domain`에서 소비하는 실행 모듈."""

import asyncio

from trading_core import Domain, cast_model

if __package__:
    from .ex07 import SwingData, SwingReq
else:
    from ex07 import SwingData, SwingReq


async def run_ex(domain: Domain) -> None:
    """`BTC`·`ETH`·`XRP`의 USD 스윙을 6건 받은 뒤 요청을 닫는다."""

    print("===== runing ex07 =====")
    req07 = SwingReq(quote="USD")
    received = 0
    async with domain.request(req07, {"BTC", "ETH", "XRP"}) as gen:
        async for data in gen:
            d = cast_model(data, SwingData)
            print(d.model_dump_json(indent=2))
            received += 1
            if received == 6:
                break
    print("===== finished ex07 =====")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex07을 실행한다."""

    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
