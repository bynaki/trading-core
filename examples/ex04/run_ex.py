"""견적 통화만 바꿔 서로 다른 원천을 구독하는 ex04 실행 모듈."""

import asyncio

from trading_core import Domain, cast_model

if __package__:
    from .ex04 import OHLCData, OHLCRequest
else:
    from ex04 import OHLCData, OHLCRequest


async def run_ex(domain: Domain) -> None:
    """USD·KRW 요청을 차례로 구독해 같은 모델로 정규화된 결과를 확인한다.

    두 요청 모두 기초 자산 심볼만 넘긴다. 앞 요청의 구독을 모두 정리한 뒤 다음
    요청을 시작하므로 상위 원천도 하나씩만 살아 있다.
    """

    print("===== runing ex04 =====")
    print('----- OHLCRequest(quote="usd", interval="5m") -----')
    req01 = OHLCRequest(quote="usd", interval="5m")
    async with domain.request(req01, {"BTC", "ETH"}) as gen:
        count = 0
        async for data in gen:
            d = cast_model(data, OHLCData)
            print(d.model_dump_json(indent=2))
            count += 1
            if count == 10:
                break
    print('----- OHLCRequest(quote="krw", interval="1h") -----')
    req02 = OHLCRequest(quote="krw", interval="1h")
    async with domain.request(req02, {"BTC", "ETH"}) as gen:
        count = 0
        async for data in gen:
            d = cast_model(data, OHLCData)
            print(d.model_dump_json(indent=2))
            count += 1
            if count == 10:
                break
    print("===== finished ex04 =====")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex04를 실행한다."""

    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
