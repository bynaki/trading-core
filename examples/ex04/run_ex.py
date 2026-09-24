"""견적 통화만 바꿔 서로 다른 원천을 구독하는 ex04 실행 모듈."""

import asyncio
from pathlib import Path

from trading_core import Domain, cast_model
from trading_core.logger import configure, get_logger

if __package__:
    from .ex04 import OHLCData, OHLCRequest
else:
    from ex04 import OHLCData, OHLCRequest

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex04")


def log_ohlc(d: OHLCData) -> None:
    """정규화된 캔들 한 건을 한 줄로 남긴다."""

    log.info(
        "수신",
        symbol=d.symbol,
        open=d.open,
        high=d.high,
        low=d.low,
        close=d.close,
        volume=d.volume,
    )


async def run_ex(domain: Domain) -> None:
    """USD·KRW 요청을 차례로 구독해 같은 모델로 정규화된 결과를 확인한다.

    두 요청 모두 기초 자산 심볼만 넘긴다. 앞 요청의 구독을 모두 정리한 뒤 다음
    요청을 시작하므로 상위 원천도 하나씩만 살아 있다.
    """

    log.info("━━━━━━━━━━ 시작: require로 상위 요청과 심볼을 함께 변환하기 ━━━━━━━━━━")
    log.info('----- OHLCRequest(quote="usd", interval="5m") -----')
    req01 = OHLCRequest(quote="usd", interval="5m")
    async with domain.stream(req01, {"BTC", "ETH"}) as gen:
        count = 0
        async for data in gen:
            log_ohlc(cast_model(data, OHLCData))
            count += 1
            if count == 10:
                break
    log.info('----- OHLCRequest(quote="krw", interval="1h") -----')
    req02 = OHLCRequest(quote="krw", interval="1h")
    async with domain.stream(req02, {"BTC", "ETH"}) as gen:
        count = 0
        async for data in gen:
            log_ohlc(cast_model(data, OHLCData))
            count += 1
            if count == 10:
                break
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex04를 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
