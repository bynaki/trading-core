"""같은 파생 요청을 서로 다른 심볼로 동시에 구독하는 ex05 예제 테스트.

핵심 명세는 하나다. **파생 스테이지가 상위 원천에 등록하는 심볼은 구독자 전체의
합집합이어야 한다.** 이 불변식이 깨지면 먼저 구독한 쪽이 조용히 굶는다.
"""

from asyncio import Queue, wait_for

import pytest

from examples.ex05 import ex05 as ex05_module
from examples.ex05 import run_ex as run_ex_module
from trading_core import DataModel, Domain, cast_model

# 데이터가 흐르지 않는 회귀가 생겨도 테스트가 멈추지 않도록 하는 상한.
RECV_TIMEOUT = 3.0


class Collector:
    """수신 심볼을 큐에 모으는 `Sender`."""

    def __init__(self) -> None:
        self._q = Queue[str]()

    async def __call__(self, data: DataModel) -> None:
        self._q.put_nowait(cast_model(data, ex05_module.PriceData).symbol)

    async def next_symbol(self) -> str:
        """다음 수신 심볼을 기다린다. 굶으면 `TimeoutError`로 실패한다."""

        return await wait_for(self._q.get(), RECV_TIMEOUT)

    def drain(self) -> None:
        """단계 경계에서 이전 단계의 잔여 수신을 비운다."""

        while not self._q.empty():
            self._q.get_nowait()


def upstream_symbols(domain: Domain) -> set[str]:
    """파생 스테이지가 상위 원천에 실제로 등록해 둔 심볼 집합."""

    content_id = ex05_module.TickRequest(venue="mockex").get_tr_content_id()
    return domain.get_origin_stage(content_id).output.symbols


def test_run_module_uses_example_models() -> None:
    """실행 모듈이 예제 모듈의 요청·데이터 모델을 그대로 사용하는지 확인한다."""

    assert run_ex_module.PriceRequest is ex05_module.PriceRequest
    assert run_ex_module.PriceData is ex05_module.PriceData
    assert callable(run_ex_module.run_ex)


def test_require_maps_symbols_to_exchange_notation() -> None:
    """require 콜백은 상위 요청을 고정하고 심볼만 거래소 표기로 바꾼다."""

    req = ex05_module.PriceRequest(quote="usd")
    upstream, symbols = req.get_tr_require_with_symbol({"BTC", "ETH"})

    assert isinstance(upstream, ex05_module.TickRequest)
    assert symbols == {"BTC/USD", "ETH/USD"}
    # 심볼이 달라도 상위 요청은 같은 스테이지를 가리켜야 한다.
    other, _ = req.get_tr_require_with_symbol({"SOL"})
    assert other.get_tr_content_id() == upstream.get_tr_content_id()


async def test_concurrent_subscribers_share_the_required_origin() -> None:
    """구독자가 늘고 줄어도 상위 원천 구독은 합집합을 따라간다.

    ex05의 세 단계를 그대로 검증한다. 두 소비자는 같은 `PriceRequest`를 서로 다른
    심볼로 동시에 구독한다.
    """

    domain = Domain()
    await domain.start()
    req = ex05_module.PriceRequest(quote="usd")
    collector_a = Collector()
    collector_b = Collector()

    try:
        # 1단계: A가 {"BTC"} 단독 구독.
        async with domain.stage(req, collector_a) as stage_a:
            await stage_a.update({"BTC"})
            assert upstream_symbols(domain) == {"BTC/USD"}
            assert await collector_a.next_symbol() == "BTC"

            # 2단계: B가 {"ETH"}로 합류. 상위에는 합집합이 등록되어야 한다.
            collector_a.drain()
            async with domain.stage(req, collector_b) as stage_b:
                await stage_b.update({"ETH"})
                assert upstream_symbols(domain) == {"BTC/USD", "ETH/USD"}
                # B가 붙었다고 A가 굶으면 안 된다.
                assert await collector_a.next_symbol() == "BTC"
                assert await collector_b.next_symbol() == "ETH"

            # 3단계: B가 떠나면 상위도 A의 심볼만 남는다.
            collector_a.drain()
            assert upstream_symbols(domain) == {"BTC/USD"}
            assert await collector_a.next_symbol() == "BTC"

        # 마지막 구독이 사라지면 파생·원천 스테이지가 모두 정리된다.
        with pytest.raises(KeyError):
            upstream_symbols(domain)
        with pytest.raises(KeyError):
            domain.get_origin_stage(req.get_tr_content_id())
    finally:
        await domain.stop()
