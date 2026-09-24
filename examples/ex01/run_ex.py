"""ex01 카운트 스트림을 실제 `Domain`에서 소비하는 실행 모듈."""

import asyncio
from pathlib import Path

from trading_core import Domain, cast_model
from trading_core.logger import configure, get_logger

if __package__:
    from .ex01 import CountData, CountReq
else:
    from ex01 import CountData, CountReq

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex01")


async def run_ex(domain: Domain) -> None:
    """카운트 10까지 출력한 뒤 요청을 닫아 정리 콜백을 실행한다."""

    log.info("━━━━━━━━━━ 시작: Domain.stream()으로 카운트 스트림 받기 ━━━━━━━━━━")
    req01 = CountReq(start=1)
    async with domain.stream(req01, {"BTC", "USDT", "ETH", "XRP"}) as gen:
        async for data in gen:
            d = cast_model(data, CountData)
            log.info("수신", symbol=d.symbol, count=d.count)
            if d.count == 10:
                break
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex01을 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
