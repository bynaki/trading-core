"""ex01 카운트 스트림을 실제 `Domain`에서 소비하는 실행 모듈."""

import asyncio

from trading_core import Domain, cast_model

if __package__:
    from .ex01 import CountData, CountReq
else:
    from ex01 import CountData, CountReq


async def run_ex(domain: Domain) -> None:
    """카운트 10까지 출력한 뒤 요청을 닫아 정리 콜백을 실행한다."""

    print("===== runing ex01 =====")
    req01 = CountReq(start=1)
    async with domain.request(req01, {"BTC", "USDT", "ETH", "XRP"}) as gen:
        async for data in gen:
            d = cast_model(data, CountData)
            print(d.model_dump_json(indent=2))
            if d.count == 10:
                break
    print("===== finished ex01 =====")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex01을 실행한다."""

    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
