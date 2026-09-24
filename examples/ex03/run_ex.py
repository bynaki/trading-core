"""두 구독이 공유하는 원천 심볼 합집합을 관찰하는 실행 모듈."""

from asyncio import gather, run, sleep
from pathlib import Path

from trading_core import Domain
from trading_core.logger import configure, get_logger

if __package__:
    from .ex03 import PriceData, PriceReq
else:
    from ex03 import PriceData, PriceReq

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex03")


class TestSender:
    """`Sender` 프로토콜에 맞춰 받은 가격 데이터를 로그로 남긴다."""

    def __init__(self, tag: str) -> None:
        self.tag = tag

    async def __call__(self, data: PriceData) -> None:
        """라우팅된 가격 데이터를 어느 구독이 받았는지와 함께 남긴다."""

        log.info(f"수신 {self.tag}", symbol=data.symbol, price=data.price)


async def run_ex(domain: Domain) -> None:
    """두 구독에서 심볼을 갱신하며 원천의 합집합을 검증한다."""

    log.info("━━━━━━━━━━ 시작: Domain.subscribe()로 구독 심볼 직접 갱신하기 ━━━━━━━━━━")
    req = PriceReq(ohlc="close")
    content_id = req.tr_content_id

    async def _(symbol_name: str, length: int) -> None:
        """개별 구독의 심볼을 추가·제거하며 원천 포함 관계를 확인한다."""

        sender = TestSender(symbol_name)
        async with domain.subscribe(req, sender) as sub:
            i = 0
            symbols: set[str] = set()
            for i in range(length):
                symbols.add(f"{symbol_name}-{i + 1}")
                await sub.update(symbols)
                shared = domain.get_shared_symbols(content_id)
                log.info(
                    f"심볼 추가 {symbol_name}",
                    symbols=sorted(symbols),
                    shared=sorted(shared),
                )
                assert symbols <= shared
                await sleep(0.5)
            for j in range(i, 0, -1):
                symbols.remove(f"{symbol_name}-{j + 1}")
                await sub.update(symbols)
                shared = domain.get_shared_symbols(content_id)
                log.info(
                    f"심볼 제거 {symbol_name}",
                    symbols=sorted(symbols),
                    shared=sorted(shared),
                )
                assert symbols <= shared
                await sleep(0.5)

    await gather(_("symbols01", 3), _("symbols02", 5))
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex03을 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    run(main())
