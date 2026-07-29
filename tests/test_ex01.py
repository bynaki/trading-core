"""`Domain.request()`로 카운트 스트림을 소비하는 ex01 예제 테스트."""

from asyncio import Queue

import pytest

from examples.ex01 import ex01 as ex01_module
from examples.ex01 import run_ex as run_ex_module
from trading_core import Domain, cast_model


def test_run_module_uses_example_models() -> None:
    """실행 모듈이 제너레이터 모듈의 요청·데이터 모델을 그대로 사용하는지 확인한다."""

    assert run_ex_module.CountReq is ex01_module.CountReq
    assert run_ex_module.CountData is ex01_module.CountData
    assert callable(run_ex_module.run_ex)


async def test_count_request_emits_from_start_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """요청 시작값부터 발행하고 스트림을 닫으면 두 수준의 정리가 실행된다."""
    sleeping = Queue[None]()
    ticks = Queue[None]()

    async def controlled_sleep(delay: float) -> None:
        assert delay == 1
        sleeping.put_nowait(None)
        await ticks.get()

    monkeypatch.setattr(ex01_module, "sleep", controlled_sleep)
    domain = Domain()
    await domain.start()

    try:
        async with domain.request(ex01_module.CountReq(start=8), {"BTC"}) as stream:
            data = []
            for index in range(3):
                data.append(cast_model(await anext(stream), ex01_module.CountData))
                await sleeping.get()
                if index < 2:
                    ticks.put_nowait(None)
    finally:
        await domain.stop()

    assert [(item.symbol, item.count) for item in data] == [
        ("BTC", 8),
        ("BTC", 9),
        ("BTC", 10),
    ]
    output = capsys.readouterr().out
    assert "Update 별로 리소스를 정리할 수 있다" in output
    assert "Stage 별로 리소스를 정리할 수 있다." in output


async def test_count_generator_rotates_across_subscribed_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """두 심볼을 구독하면 카운트마다 다른 심볼을 번갈아 선택한다."""
    sleeping = Queue[None]()
    ticks = Queue[None]()

    async def controlled_sleep(delay: float) -> None:
        assert delay == 1
        sleeping.put_nowait(None)
        await ticks.get()

    monkeypatch.setattr(ex01_module, "sleep", controlled_sleep)
    domain = Domain()
    await domain.start()

    try:
        async with domain.request(ex01_module.CountReq(start=6), {"BTC", "ETH"}) as stream:
            data = []
            for index in range(4):
                data.append(cast_model(await anext(stream), ex01_module.CountData))
                await sleeping.get()
                if index < 3:
                    ticks.put_nowait(None)
    finally:
        await domain.stop()

    assert [item.count for item in data] == [6, 7, 8, 9]
    symbols = [item.symbol for item in data]
    assert set(symbols) == {"BTC", "ETH"}
    assert all(
        current != following for current, following in zip(symbols, symbols[1:], strict=False)
    )


async def test_zero_start_finishes_without_emitting_data() -> None:
    """`start=0`이면 binder의 반복 조건이 거짓이라 데이터를 발행하지 않는다."""
    request = ex01_module.CountReq(start=0)
    context = ex01_module.gen01(request)
    bind = ex01_module.gen01.get_binder(context, {"BTC"}, None)

    assert bind is not None
    assert [item async for item in bind()] == []
