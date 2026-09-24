"""ex07 스윙 스트림을 실제 `Domain`에서 소비하는 실행 모듈.

`Domain.stream()`을 쓰는 이유는 ex01과 같다. 이 예제가 보여 주려는 것은 세션 요청
스테이지가 심볼별 슬롯과 파이프라인을 엮는 방식이지, 구독을 실행 중에 바꾸는 것이 아니다.
심볼 집합을 바꿔 가며 관찰하는 쪽은 ex03·ex05·ex06이다.
"""

import asyncio
from pathlib import Path

from trading_core import Domain, cast_model
from trading_core.logger import configure, get_logger

if __package__:
    from .ex07 import SwingData, SwingReq
else:
    from ex07 import SwingData, SwingReq

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex07")


async def run_ex(domain: Domain) -> None:
    """`BTC`·`ETH`·`XRP`의 USD 스윙을 6건 받은 뒤 요청을 닫는다.

    구독은 하위 표기(`"BTC"`)로 하지만 상위 원천에는 `"BTC/USD"`가 올라간다. 받는
    데이터의 `symbol`이 다시 `"BTC"`인 것이 이 예제의 관전 포인트다.
    """

    log.info("━━━━━━━━━━ 시작: SessionRequest로 심볼마다 파이프라인 붙이기 ━━━━━━━━━━")
    req07 = SwingReq(quote="USD")
    received = 0
    async with domain.stream(req07, {"BTC", "ETH", "XRP"}) as gen:
        async for data in gen:
            d = cast_model(data, SwingData)
            log.info("수신", symbol=d.symbol, quote=d.quote, price=d.price, swing=d.swing)
            received += 1
            if received == 6:
                break
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex07을 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
