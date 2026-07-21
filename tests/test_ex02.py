"""의존 요청과 공유 원천으로 구성된 ex02 예제 테스트."""

from asyncio import Event
from collections.abc import Iterator
from typing import Literal

import pytest

from examples import ex02
from examples.ex02 import origin, refer
from trading_core import Domain, TransmitQueue, cast_model


@pytest.fixture(autouse=True)
def clean_example_contexts() -> Iterator[None]:
    """각 테스트가 ex02의 클래스 수준 컨텍스트 저장소를 독립적으로 사용하게 한다."""
    origin.NamingAllContext.cxt_dict.clear()
    refer.NamingContext.cxt_dict.clear()
    yield
    origin.NamingAllContext.cxt_dict.clear()
    refer.NamingContext.cxt_dict.clear()


def test_naming_request_builds_required_origin_request() -> None:
    """NamingReq가 kind를 제외한 count 조건으로 NamingAllReq 의존성을 만드는지 확인한다."""
    request = ex02.NamingReq(kind="flower", count=3)

    required = request.tr_require

    assert isinstance(required, ex02.NamingAllReq)
    assert required.count == 3


async def test_origin_generator_emits_total_count_across_sorted_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원천이 정렬된 심볼을 순환하며 요청한 전체 개수만큼 묶음 데이터를 발행한다."""

    async def no_sleep(delay: float) -> None:
        assert delay == 1

    monkeypatch.setattr(origin, "sleep", no_sleep)
    context = origin.naming(ex02.NamingAllReq(count=4))
    bind = origin.naming.get_binder(context, {"SYMBOL_B", "SYMBOL_A"}, None)
    close = origin.naming.get_closer(context)

    assert bind is not None
    assert close is not None
    try:
        data = [cast_model(item, ex02.NamingAllData) async for item in bind()]
    finally:
        await close()

    assert [item.count for item in data] == [1, 2, 3, 4]
    assert [item.symbol for item in data] == [
        "SYMBOL_A",
        "SYMBOL_B",
        "SYMBOL_A",
        "SYMBOL_B",
    ]
    assert [(item.flower, item.dog, item.cat) for item in data[:2]] == [
        ("Rose:SYMBOL_A", "Golden Retriever:SYMBOL_A", "Luna:SYMBOL_A"),
        ("Tulip:SYMBOL_B", "Labrador Retriever:SYMBOL_B", "Oliver:SYMBOL_B"),
    ]


@pytest.mark.parametrize(
    ("kind", "expected_name"),
    [
        ("flower", "Rose:SYMBOL_A"),
        ("dog", "Golden Retriever:SYMBOL_A"),
        ("cat", "Luna:SYMBOL_A"),
    ],
)
async def test_naming_request_transforms_required_data_through_domain(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["flower", "dog", "cat"],
    expected_name: str,
) -> None:
    """Domain이 원천 의존성을 연결하고 요청한 종류만 NamingData로 변환하는지 확인한다."""

    async def no_sleep(delay: float) -> None:
        assert delay == 1

    monkeypatch.setattr(origin, "sleep", no_sleep)
    domain = Domain()
    await domain.start()

    try:
        request = ex02.NamingReq(kind=kind, count=1)
        async with domain.request(request, {"SYMBOL_A"}) as stream:
            data = [cast_model(item, ex02.NamingData) async for item in stream]
    finally:
        await domain.stop()

    assert [(item.symbol, item.name, item.count) for item in data] == [
        ("SYMBOL_A", expected_name, 1)
    ]
    assert refer.NamingContext.cxt_dict == {}
    assert origin.NamingAllContext.cxt_dict == {}


async def test_matching_transform_requests_and_kinds_share_origin_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 변환 요청은 컨텍스트를 공유하고 서로 다른 종류도 공통 원천을 공유한다."""
    release = Event()

    async def wait_for_release(delay: float) -> None:
        assert delay == 1
        await release.wait()

    monkeypatch.setattr(origin, "sleep", wait_for_release)
    domain = Domain()
    await domain.start()

    try:
        flower = ex02.NamingReq(kind="flower", count=10)
        dog = ex02.NamingReq(kind="dog", count=10)
        async with domain.stage(flower, TransmitQueue()) as first_flower:
            await first_flower.update({"SYMBOL_A"})
            assert len(refer.NamingContext.cxt_dict) == 1
            assert len(origin.NamingAllContext.cxt_dict) == 1

            async with domain.stage(flower, TransmitQueue()) as second_flower:
                await second_flower.update({"SYMBOL_B"})
                assert len(refer.NamingContext.cxt_dict) == 1
                assert len(origin.NamingAllContext.cxt_dict) == 1

                async with domain.stage(dog, TransmitQueue()) as dog_stage:
                    await dog_stage.update({"SYMBOL_C"})
                    assert len(refer.NamingContext.cxt_dict) == 2
                    assert len(origin.NamingAllContext.cxt_dict) == 1

                assert len(refer.NamingContext.cxt_dict) == 1
                assert len(origin.NamingAllContext.cxt_dict) == 1

        assert refer.NamingContext.cxt_dict == {}
        assert origin.NamingAllContext.cxt_dict == {}
    finally:
        release.set()
        await domain.stop()
