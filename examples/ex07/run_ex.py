"""ex07 스윙 스트림을 실제 `Domain`에서 소비하는 실행 모듈.

`Domain.request()`를 쓰는 이유는 ex01과 같다. 이 예제가 보여 주려는 것은 요청형
스테이지가 심볼별 슬롯과 시퀀스를 엮는 방식이지, 구독을 실행 중에 바꾸는 것이 아니다.
심볼 집합을 바꿔 가며 관찰하는 쪽은 ex03·ex05·ex06이다.
"""

import asyncio

from trading_core import Domain, cast_model

if __package__:
    from .ex07 import SwingData, SwingReq
else:
    from ex07 import SwingData, SwingReq


async def run_ex(domain: Domain) -> None:
    """`BTC`·`ETH`·`XRP`의 USD 스윙을 6건 받은 뒤 요청을 닫는다.

    구독은 하위 표기(`"BTC"`)로 하지만 상위 원천에는 `"BTC/USD"`가 올라간다. 받는
    데이터의 `symbol`이 다시 `"BTC"`인 것이 이 예제의 관전 포인트다.
    """

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
