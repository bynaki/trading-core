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


async def test_count_generator_cleans_up_when_closed_early(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """예제 제너레이터를 조기에 닫아도 정리 구문이 실행되는지 확인한다."""
    request = ex01.CountReq(start=0)
    bind = ex01.gen01.get_binder(ex01.gen01(request), {"ETH"}, None)

    assert bind is not None
    stream = bind()
    first = await anext(stream)
    await stream.aclose()

    assert isinstance(first, ex01.CountModel)
    assert (first.symbol, first.model_dump()["count"]) == ("ETH", 1)
    assert capsys.readouterr().out == "Must resource cleaned up - count: 1\n"
