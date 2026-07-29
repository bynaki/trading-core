"""두 `Stage`가 공유하는 원천 심볼 합집합을 관찰하는 실행 모듈."""

from asyncio import gather, run, sleep

from trading_core import Domain

if __package__:
    from .ex03 import PriceData, PriceReq
else:
    from ex03 import PriceData, PriceReq


class TestSender:
    """`Sender` 프로토콜에 맞춰 받은 가격 데이터를 출력한다."""

    async def __call__(self, data: PriceData) -> None:
        """스테이지가 라우팅한 가격 데이터를 JSON으로 출력한다."""

        print(data.model_dump_json(indent=2))


async def run_ex(domain: Domain) -> None:
    """두 스테이지에서 심볼을 갱신하며 원천의 합집합을 검증한다."""

    print("===== runing ex03 =====")
    req = PriceReq(ohlc="close")
    content_id = req.get_tr_content_id()

    async def _(symbol_name: str, length: int) -> None:
        """개별 스테이지의 심볼을 추가·제거하며 원천 포함 관계를 확인한다."""

        sender = TestSender()
        async with domain.stage(req, sender) as stage:
            i = 0
            symbols: set[str] = set()
            for i in range(length):
                symbols.add(f"{symbol_name}-{i + 1}")
                await stage.update(symbols)
                origin = domain.get_origin_stage(content_id)
                print(f"symbols: {symbols}")
                print(f"orgin.symbols: {origin.output.symbols}")
                assert (symbols & origin.output.symbols) == symbols
                await sleep(1)
            for j in range(i, 0, -1):
                symbols.remove(f"{symbol_name}-{j + 1}")
                await stage.update(symbols)
                origin = domain.get_origin_stage(content_id)
                print(f"symbols: {symbols}")
                print(f"orgin.symbols: {origin.output.symbols}")
                assert (symbols & origin.output.symbols) == symbols
                await sleep(1)

    await gather(_("symbols01", 3), _("symbols02", 5))
    print("===== finished ex03 =====")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex03을 실행한다."""

    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    run(main())
