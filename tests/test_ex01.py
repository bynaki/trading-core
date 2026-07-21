"""카운트 제너레이터 예제 테스트."""

import sys
from pathlib import Path

import pytest

from trading_core import Domain


def _load_example():
    project_root = str(Path(__file__).parents[1])
    sys.path.insert(0, project_root)
    try:
        from examples import ex01
    finally:
        sys.path.remove(project_root)
    return ex01


ex01 = _load_example()


async def test_count_generator_through_domain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """예제의 Domain 요청 흐름이 다음 카운트부터 10까지 발행하는지 확인한다."""

    async def no_sleep(delay: float) -> None:
        assert delay == 1

    monkeypatch.setattr(ex01, "sleep", no_sleep)
    domain = Domain()
    await domain.start()

    try:
        async with domain.request(ex01.CountReq(start=8), {"BTC"}) as stream:
            data = [
                await anext(stream),
                await anext(stream),
            ]
    finally:
        await domain.stop()

    assert all(isinstance(item, ex01.CountModel) for item in data)
    assert [(item.symbol, item.model_dump()["count"]) for item in data] == [
        ("BTC", 9),
        ("BTC", 10),
    ]
    assert "Must resource cleaned up - count: 10" in capsys.readouterr().out


async def test_count_generator_rotates_across_subscribed_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """여러 심볼을 구독하면 카운트마다 심볼을 번갈아 발행하는지 확인한다."""

    async def no_sleep(delay: float) -> None:
        assert delay == 1

    monkeypatch.setattr(ex01, "sleep", no_sleep)
    domain = Domain()
    await domain.start()

    try:
        async with domain.request(ex01.CountReq(start=6), {"BTC", "ETH"}) as stream:
            data = [item async for item in stream]
    finally:
        await domain.stop()

    assert [item.model_dump()["count"] for item in data] == [7, 8, 9, 10]
    symbols = [item.symbol for item in data]
    assert set(symbols) == {"BTC", "ETH"}
    assert all(
        current != following for current, following in zip(symbols, symbols[1:], strict=False)
    )


async def test_count_generator_cleans_up_when_closed_early(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Domain 요청을 조기에 닫아도 원천 제너레이터의 정리 구문이 실행되는지 확인한다."""
    domain = Domain()
    await domain.start()

    try:
        async with domain.request(ex01.CountReq(start=0), {"ETH"}) as stream:
            first = await anext(stream)
    finally:
        await domain.stop()

    assert isinstance(first, ex01.CountModel)
    assert (first.symbol, first.model_dump()["count"]) == ("ETH", 1)
    assert "Must resource cleaned up - count: 1" in capsys.readouterr().out
