"""동적 심볼 갱신과 공유 원천을 보여주는 ex03 예제 테스트."""

from asyncio import Event, Queue
from collections.abc import Sequence

import pytest

from examples.ex03 import ex03 as ex03_module
from examples.ex03 import run_ex as run_ex_module
from trading_core import DataModel, Domain, cast_model


class RecordingSender:
    """스테이지가 전달한 데이터를 테스트에서 확인할 수 있도록 모은다."""

    def __init__(self) -> None:
        self.received: list[DataModel] = []

    async def __call__(self, data: DataModel) -> None:
        self.received.append(data)


@pytest.mark.parametrize(
    ("ohlc", "quantity"),
    [("open", 10), ("high", 1000), ("low", 1), ("close", 100)],
)
def test_price_context_uses_ohlc_quantity(ohlc: str, quantity: int) -> None:
    """OHLC 종류별 증가 단위가 심볼마다 독립적으로 누적된다."""
    request = ex03_module.PriceReq(ohlc=ohlc)  # type: ignore[arg-type]
    context = ex03_module.price(request)

    assert context.price("BTC") == quantity
    assert context.price("BTC") == quantity * 2
    assert context.price("ETH") == quantity


async def test_price_binder_selects_subscribed_symbols_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """binder가 구독 심볼만 선택하고 닫힐 때 업데이트 자원을 정리한다."""
    selected = iter(["BTC", "ETH", "BTC"])

    def choose(symbols: Sequence[str]) -> str:
        symbol = next(selected)
        assert symbol in symbols
        return symbol

    async def no_sleep(delay: float) -> None:
        assert delay == 1

    monkeypatch.setattr(ex03_module.random, "choice", choose)
    monkeypatch.setattr(ex03_module, "sleep", no_sleep)
    context = ex03_module.price(ex03_module.PriceReq(ohlc="close"))
    bind = ex03_module.price.get_binder(context, {"BTC", "ETH"}, None)

    assert bind is not None
    stream = bind()
    try:
        data = [cast_model(await anext(stream), ex03_module.PriceData) for _ in range(3)]
    finally:
        await stream.aclose()

    assert [(item.symbol, item.price) for item in data] == [
        ("BTC", 100),
        ("ETH", 100),
        ("BTC", 200),
    ]
    assert context.updating_count == 1
    assert "Update 별로 자원을 정리할 수 있다." in capsys.readouterr().out


async def test_equal_requests_share_origin_and_union_subscriptions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """같은 요청의 두 Stage가 원천 하나와 구독 심볼 합집합을 공유한다."""
    release = Event()
    started = Queue[None]()

    def choose(symbols: Sequence[str]) -> str:
        return sorted(symbols)[0]

    async def wait_for_release(delay: float) -> None:
        assert delay == 1
        started.put_nowait(None)
        await release.wait()

    monkeypatch.setattr(ex03_module.random, "choice", choose)
    monkeypatch.setattr(ex03_module, "sleep", wait_for_release)
    request = ex03_module.PriceReq(ohlc="close")
    content_id = request.get_tr_content_id()
    domain = Domain()
    await domain.start()

    try:
        async with domain.stage(request, RecordingSender()) as first:
            await first.update({"BTC"})
            await started.get()
            origin = domain.get_origin_stage(content_id)
            assert origin.output.symbols == {"BTC"}

            async with domain.stage(
                ex03_module.PriceReq(ohlc="close"), RecordingSender()
            ) as second:
                await second.update({"ETH"})
                await started.get()
                assert domain.get_origin_stage(content_id) is origin
                assert origin.output.symbols == {"BTC", "ETH"}

            await started.get()
            assert origin.output.symbols == {"BTC"}

        with pytest.raises(KeyError):
            domain.get_origin_stage(content_id)
    finally:
        release.set()
        await domain.stop()

    output = capsys.readouterr().out
    assert output.count("Updating Stage") == 3
    assert "Detached Stage" in output


def test_run_module_uses_price_models() -> None:
    """실행 모듈의 sender와 요청 흐름이 ex03 모델을 사용한다."""

    assert run_ex_module.PriceReq is ex03_module.PriceReq
    assert run_ex_module.PriceData is ex03_module.PriceData
    assert callable(run_ex_module.run_ex)
