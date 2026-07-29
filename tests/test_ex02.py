"""의존 요청과 공유 원천으로 구성된 ex02 예제 테스트."""

from asyncio import Event, Queue
from collections.abc import Iterator
from typing import Literal

import pytest

from examples import ex02
from examples.ex02 import origin, refer
from trading_core import Domain, TransmitQueue, cast_model


def test_package_exports_example_api() -> None:
    """ex02 패키지가 문서에 소개한 모델과 실행 함수를 공개한다."""

    assert ex02.NamingAllReq is origin.NamingAllReq
    assert ex02.NamingAllData is origin.NamingAllData
    assert ex02.NamingReq is refer.NamingReq
    assert ex02.NamingData is refer.NamingData
    assert callable(ex02.run_ex)


@pytest.fixture(autouse=True)
def clean_example_contexts() -> Iterator[None]:
    """각 테스트가 클래스 수준 컨텍스트 저장소를 독립적으로 사용하게 한다."""
    origin.NamingAllContext.cxt_dict.clear()
    refer.NamingContext.cxt_dict.clear()
    yield
    origin.NamingAllContext.cxt_dict.clear()
    refer.NamingContext.cxt_dict.clear()


def test_naming_requests_build_the_same_required_origin() -> None:
    """서로 다른 이름 종류도 필드 없는 동일한 원천 요청을 요구한다."""
    flower_required = ex02.NamingReq(kind="flower").tr_require
    dog_required = ex02.NamingReq(kind="dog").tr_require

    assert isinstance(flower_required, ex02.NamingAllReq)
    assert isinstance(dog_required, ex02.NamingAllReq)
    assert flower_required.get_tr_content_id() == dog_required.get_tr_content_id()


async def test_origin_generator_emits_across_sorted_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원천 binder가 정렬한 심볼을 순환하며 세 종류의 이름을 함께 발행한다."""

    async def no_sleep(delay: float) -> None:
        assert delay == 1

    monkeypatch.setattr(origin, "sleep", no_sleep)
    context = origin.naming(ex02.NamingAllReq())
    bind = origin.naming.get_binder(context, {"SYMBOL_B", "SYMBOL_A"}, None)
    close = origin.naming.get_closer(context)

    assert bind is not None
    assert close is not None
    stream = bind()
    try:
        data = [cast_model(await anext(stream), ex02.NamingAllData) for _ in range(4)]
    finally:
        await stream.aclose()
        await close()

    assert context.count == 1
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
    assert origin.NamingAllContext.cxt_dict == {}


@pytest.mark.parametrize(
    ("kind", "expected_name"),
    [
        ("flower", "Rose:SYMBOL_A - flower"),
        ("dog", "Golden Retriever:SYMBOL_A - dog"),
        ("cat", "Luna:SYMBOL_A - cat"),
    ],
)
async def test_naming_request_transforms_required_data_through_domain(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["flower", "dog", "cat"],
    expected_name: str,
) -> None:
    """Domain이 의존 원천을 연결하고 요청한 종류만 파생 모델로 변환한다."""
    sleeping = Event()
    release = Event()

    async def controlled_sleep(delay: float) -> None:
        assert delay == 1
        sleeping.set()
        await release.wait()

    monkeypatch.setattr(origin, "sleep", controlled_sleep)
    domain = Domain()
    await domain.start()

    try:
        request = ex02.NamingReq(kind=kind)
        async with domain.request(request, {"SYMBOL_A"}) as stream:
            item = cast_model(await anext(stream), ex02.NamingData)
            await sleeping.wait()
    finally:
        release.set()
        await domain.stop()

    assert (item.symbol, item.name) == ("SYMBOL_A", expected_name)
    assert refer.NamingContext.cxt_dict == {}
    assert origin.NamingAllContext.cxt_dict == {}


async def test_matching_kinds_share_transform_and_all_kinds_share_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 kind는 파생 컨텍스트를, 모든 kind는 공통 원천 컨텍스트를 공유한다."""
    release = Event()
    started = Queue[None]()

    async def wait_for_release(delay: float) -> None:
        assert delay == 1
        started.put_nowait(None)
        await release.wait()

    monkeypatch.setattr(origin, "sleep", wait_for_release)
    domain = Domain()
    await domain.start()

    try:
        flower = ex02.NamingReq(kind="flower")
        dog = ex02.NamingReq(kind="dog")
        async with domain.stage(flower, TransmitQueue()) as first_flower:
            await first_flower.update({"SYMBOL_A"})
            await started.get()
            assert len(refer.NamingContext.cxt_dict) == 1
            assert len(origin.NamingAllContext.cxt_dict) == 1

            async with domain.stage(flower, TransmitQueue()) as second_flower:
                await second_flower.update({"SYMBOL_B"})
                await started.get()
                assert len(refer.NamingContext.cxt_dict) == 1
                assert len(origin.NamingAllContext.cxt_dict) == 1

                async with domain.stage(dog, TransmitQueue()) as dog_stage:
                    await dog_stage.update({"SYMBOL_C"})
                    await started.get()
                    assert len(refer.NamingContext.cxt_dict) == 2
                    assert len(origin.NamingAllContext.cxt_dict) == 1

                assert len(refer.NamingContext.cxt_dict) == 1
                assert len(origin.NamingAllContext.cxt_dict) == 1

        assert refer.NamingContext.cxt_dict == {}
        assert origin.NamingAllContext.cxt_dict == {}
    finally:
        release.set()
        await domain.stop()
