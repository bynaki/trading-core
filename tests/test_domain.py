"""`domain.py` 명세 — 원천 공유, 심볼 합집합, 재시작 조건, 정리 지점.

테스트끼리는 요청의 `tag` 값을 달리해 격리한다. 같은 `tag`는 같은 content_id이고,
곧 같은 원천 스테이지와 같은 기록(`log_of`)을 뜻한다.
"""

from typing import Any, cast

import pytest

from trading_core import Domain, DomainError, Stage, cast_model, get_model_inst_id

from .support.harness import Recorder, wait_until
from .support.streams import (
    QUOTE_SUFFIX,
    CounterData,
    CounterReq,
    DerivedData,
    DerivedReq,
    MappedReq,
    UnboundReq,
    log_of,
)


def origin_symbols(domain: Domain, req: CounterReq | DerivedReq | MappedReq) -> set[str]:
    """요청의 원천 스테이지가 현재 들고 있는 심볼 합집합."""

    return domain.get_origin_stage(req.get_tr_content_id()).output.symbols


def mapped(symbols: set[str]) -> frozenset[str]:
    """`MappedReq`의 require가 하위 심볼을 바꿔 상위에 올리는 표기."""

    return frozenset(f"{s}{QUOTE_SUFFIX}" for s in symbols)


# ===== Domain.request() =====


async def test_request_streams_data_and_cleans_up(domain: Domain):
    """`request()`는 구독한 심볼의 데이터만 주고, 빠져나오면 스테이지를 정리한다."""

    req = CounterReq(tag="request-basic")
    log = log_of(req)
    received: list[CounterData] = []

    async with domain.request(req, {"BTC", "ETH"}) as gen:
        async for data in gen:
            received.append(cast_model(data, CounterData))
            if len(received) == 4:
                break

    assert {d.symbol for d in received} == {"BTC", "ETH"}
    assert log.inits == 1
    assert log.starts == [frozenset({"BTC", "ETH"})]
    assert log.stopped == 1  # 업데이트 단위 정리(generator의 finally)
    assert log.detached == 1  # 스테이지 단위 정리
    with pytest.raises(KeyError):
        domain.get_origin_stage(req.get_tr_content_id())


async def test_request_without_binder_raises_domain_error(domain: Domain):
    """binder가 없는 요청은 `DomainError`."""

    # 스테이지는 첫 소비 시점에 만들어지므로 그때 예외가 난다.
    with pytest.raises(DomainError):
        async with domain.request(UnboundReq(tag="none"), {"BTC"}) as gen:
            async for _ in gen:
                break


# ===== content_id 단위 공유 =====


async def test_equal_requests_share_one_origin_stage(domain: Domain):
    """필드 값이 같은 요청은 인스턴스가 달라도 하나의 원천 스테이지를 공유한다."""

    tag = "shared-origin"
    req_a, req_b = CounterReq(tag=tag), CounterReq(tag=tag)
    assert get_model_inst_id(req_a) != get_model_inst_id(req_b)
    assert req_a.get_tr_content_id() == req_b.get_tr_content_id()
    log = log_of(req_a)
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.stage(req_a, rec_a) as stage_a, domain.stage(req_b, rec_b) as stage_b:
        await stage_a.update({"BTC"})
        await stage_b.update({"ETH"})
        assert domain.get_origin_stage(req_a.get_tr_content_id()) is domain.get_origin_stage(
            req_b.get_tr_content_id()
        )
        assert origin_symbols(domain, req_a) == {"BTC", "ETH"}
        await rec_a.wait_for(2)
        await rec_b.wait_for(2)

    assert log.inits == 1  # 컨텍스트도 공유한다
    assert rec_a.symbols == {"BTC"}  # 출력은 구독한 심볼로만 fan-out된다
    assert rec_b.symbols == {"ETH"}
    assert log.detached == 1


async def test_different_field_values_get_separate_stages(domain: Domain):
    """필드 값이 다르면 별개의 원천 스테이지를 갖는다."""

    req_a, req_b = CounterReq(tag="separate-a"), CounterReq(tag="separate-b")
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.stage(req_a, rec_a) as stage_a, domain.stage(req_b, rec_b) as stage_b:
        await stage_a.update({"BTC"})
        await stage_b.update({"BTC"})
        assert domain.get_origin_stage(req_a.get_tr_content_id()) is not domain.get_origin_stage(
            req_b.get_tr_content_id()
        )
        assert log_of(req_a).inits == 1
        assert log_of(req_b).inits == 1


# ===== 심볼 합집합과 재시작 조건 =====


async def test_origin_restarts_only_when_the_union_changes(domain: Domain):
    """generator는 심볼 합집합이 실제로 달라질 때만 재시작한다.

    재시작은 태스크 제출로 이어지므로 `starts` 기록은 `update()` 직후가 아니라
    새 태스크가 실행된 뒤에 늘어난다. 그래서 "재시작했다"는 기다려서 확인하고,
    "재시작하지 않았다"는 데이터가 흐른 뒤에도 그대로임을 확인한다.
    """

    tag = "union-restart"
    req = CounterReq(tag=tag)
    log = log_of(req)
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.stage(req, rec_a) as stage_a:
        await stage_a.update({"BTC", "ETH"})
        await rec_a.wait_for(1)
        assert log.starts == [frozenset({"BTC", "ETH"})]

        async with domain.stage(req, rec_b) as stage_b:
            # 이미 합집합에 있는 심볼만 구독하면 합집합이 그대로라 재시작하지 않는다.
            await stage_b.update({"BTC"})
            await rec_b.wait_for(1)
            assert rec_b.symbols == {"BTC"}
            assert log.starts == [frozenset({"BTC", "ETH"})]

            # 합집합이 넓어지면 재시작한다.
            await stage_b.update({"BTC", "SOL"})
            assert origin_symbols(domain, req) == {"BTC", "ETH", "SOL"}
            await wait_until(lambda: len(log.starts) == 2, "합집합이 넓어졌는데 재시작하지 않았다.")
            assert log.last_start == frozenset({"BTC", "ETH", "SOL"})

        # 구독이 빠져도 합집합이 달라지므로 재시작한다.
        assert origin_symbols(domain, req) == {"BTC", "ETH"}
        await wait_until(lambda: len(log.starts) == 3, "구독이 빠졌는데 재시작하지 않았다.")
        assert log.last_start == frozenset({"BTC", "ETH"})

    assert log.stopped == 3  # 재시작 2번 + 마지막 정리 1번
    assert log.detached == 1


async def test_update_replaces_symbols_and_empty_set_unsubscribes(domain: Domain):
    """`update()`는 추가가 아니라 교체이고, 빈 집합은 구독 해제다."""

    req = CounterReq(tag="update-replace")
    log = log_of(req)
    recorder = Recorder()

    async with domain.stage(req, recorder) as stage:
        await stage.update({"BTC"})
        assert origin_symbols(domain, req) == {"BTC"}

        await stage.update({"ETH"})
        assert origin_symbols(domain, req) == {"ETH"}

        await stage.update(set())
        with pytest.raises(KeyError):
            domain.get_origin_stage(req.get_tr_content_id())
        assert log.detached == 1


async def test_stage_symbols_are_always_contained_in_the_origin_union(domain: Domain):
    """각 스테이지의 심볼은 언제나 원천 합집합에 포함된다."""

    req = CounterReq(tag="containment")
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.stage(req, rec_a) as stage_a, domain.stage(req, rec_b) as stage_b:
        symbols_a: set[str] = set()
        symbols_b: set[str] = set()
        for i in range(3):
            symbols_a.add(f"A-{i}")
            symbols_b.add(f"B-{i}")
            await stage_a.update(symbols_a)
            await stage_b.update(symbols_b)
            union = origin_symbols(domain, req)
            assert symbols_a <= union
            assert symbols_b <= union
            assert union == symbols_a | symbols_b


# ===== 의존 스트림 =====


async def test_dependent_stage_creates_and_shares_the_upstream(domain: Domain):
    """파생 스테이지는 상위 원천을 만들어 쓰고, 끝나면 함께 정리한다."""

    tag = "dependent-basic"
    req = DerivedReq(tag=tag)
    upstream = CounterReq(tag=tag)
    dep_log, up_log = log_of(req), log_of(upstream)
    recorder = Recorder()

    async with domain.stage(req, recorder) as stage:
        await stage.update({"BTC"})
        await recorder.wait_for(2)
        assert origin_symbols(domain, upstream) == {"BTC"}
        assert up_log.starts == [frozenset({"BTC"})]
        assert {d.symbol for d in recorder.received} == {"BTC"}
        assert isinstance(recorder.received[0], DerivedData)

    assert dep_log.detached == 1
    assert up_log.detached == 1
    with pytest.raises(KeyError):
        domain.get_origin_stage(req.get_tr_content_id())
    with pytest.raises(KeyError):
        domain.get_origin_stage(upstream.get_tr_content_id())


async def test_dependent_stages_with_same_upstream_share_it(domain: Domain):
    """상위 요청의 content_id가 같으면 파생 스테이지가 달라도 원천을 공유한다."""

    tag = "dependent-shared-upstream"
    upstream = CounterReq(tag=tag)
    derived_req, mapped_req = DerivedReq(tag=tag), MappedReq(tag=tag)
    rec_derived, rec_mapped = Recorder("derived"), Recorder("mapped")

    async with (
        domain.stage(derived_req, rec_derived) as stage_derived,
        domain.stage(mapped_req, rec_mapped) as stage_mapped,
    ):
        await stage_derived.update({"BTC/USD"})  # 변환 없이 상위 표기를 그대로 구독한다
        await stage_mapped.update({"ETH"})  # 변환되어 "ETH/USD"로 올라간다
        assert origin_symbols(domain, upstream) == {"BTC/USD", "ETH/USD"}
        assert log_of(upstream).inits == 1
        await rec_derived.wait_for(1)
        await rec_mapped.wait_for(1)

    assert rec_derived.symbols == {"BTC/USD"}
    assert rec_mapped.symbols == {"ETH"}
    assert log_of(upstream).detached == 1


async def test_dependent_registers_the_union_upstream(domain: Domain):
    """파생 스테이지가 상위에 등록하는 심볼은 **구독자 전체의 합집합**이어야 한다.

    이 불변식이 깨지면 나중에 붙은 구독이 앞선 구독의 상위 등록을 덮어써, 먼저
    구독한 쪽이 아무 오류 없이 조용히 굶는다(ex05가 회귀 테스트로 남긴 사례).
    """

    tag = "dependent-union"
    req = MappedReq(tag=tag)
    upstream = CounterReq(tag=tag)
    up_log = log_of(upstream)
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.stage(req, rec_a) as stage_a:
        await stage_a.update({"BTC"})
        await rec_a.wait_for(1)
        assert up_log.last_start == frozenset({f"BTC{QUOTE_SUFFIX}"})

        async with domain.stage(req, rec_b) as stage_b:
            await stage_b.update({"ETH"})
            # 상위에는 A와 B의 합집합이 올라가야 한다.
            upstream_union = {f"BTC{QUOTE_SUFFIX}", f"ETH{QUOTE_SUFFIX}"}
            assert origin_symbols(domain, upstream) == upstream_union
            await wait_until(
                lambda: up_log.last_start == frozenset(upstream_union),
                "상위 generator가 합집합으로 재시작하지 않았다.",
            )

            # B가 붙은 뒤에도 A는 계속 데이터를 받는다.
            rec_a.clear()
            await rec_a.wait_for(1)
            await rec_b.wait_for(1)

        # B가 떠나면 상위 구독도 A의 몫만 남는다.
        assert origin_symbols(domain, upstream) == {f"BTC{QUOTE_SUFFIX}"}
        rec_a.clear()
        await rec_a.wait_for(1)

    assert rec_a.symbols == {"BTC"}
    assert rec_b.symbols == {"ETH"}


async def test_dependent_restarts_only_when_the_union_changes(domain: Domain):
    """파생 스테이지도 심볼 합집합이 실제로 달라질 때만 재시작한다.

    `test_origin_restarts_only_when_the_union_changes`와 같은 규칙을 dependent 분기에서
    확인한다. 파생 쪽은 상위 원천까지 함께 움직이므로 두 계층의 기록을 나란히 본다.

    새 구독자가 데이터를 받는지도 함께 단정한다. 조기 반환이 `set_sender()` **뒤에**
    있어야 재시작 없이도 구독자 목록에 들어가기 때문이다. 순서가 뒤바뀌면 재시작
    횟수는 그대로면서 새 구독자만 다음 재시작까지 굶는다. (ex06과 같은 시나리오다.)
    """

    tag = "dependent-union-restart"
    req = MappedReq(tag=tag)
    upstream = CounterReq(tag=tag)
    dep_log, up_log = log_of(req), log_of(upstream)
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.stage(req, rec_a) as stage_a:
        await stage_a.update({"BTC"})
        await rec_a.wait_for(1)
        assert dep_log.starts == [frozenset({"BTC"})]
        assert up_log.starts == [mapped({"BTC"})]

        async with domain.stage(req, rec_b) as stage_b:
            # 이미 합집합에 있는 심볼이므로 두 계층 모두 재시작하지 않아야 한다.
            await stage_b.update({"BTC"})
            await rec_b.wait_for(1)
            assert rec_b.symbols == {"BTC"}
            assert origin_symbols(domain, req) == {"BTC"}
            assert origin_symbols(domain, upstream) == set(mapped({"BTC"}))
            assert len(dep_log.starts) == 1
            assert len(up_log.starts) == 1
            # 재시작이 없었으니 기존 generator의 finally도 아직 돌지 않았다.
            assert dep_log.stopped == 0
            assert up_log.stopped == 0

            # 합집합이 넓어지면 두 계층이 함께 재시작한다.
            await stage_b.update({"BTC", "ETH"})
            assert origin_symbols(domain, req) == {"BTC", "ETH"}
            assert origin_symbols(domain, upstream) == set(mapped({"BTC", "ETH"}))
            await wait_until(
                lambda: len(dep_log.starts) == 2 and len(up_log.starts) == 2,
                "합집합이 넓어졌는데 재시작하지 않았다.",
            )
            assert dep_log.last_start == frozenset({"BTC", "ETH"})
            assert up_log.last_start == mapped({"BTC", "ETH"})

        # B가 떠나 합집합이 좁아져도 재시작한다.
        assert origin_symbols(domain, req) == {"BTC"}
        await wait_until(
            lambda: len(dep_log.starts) == 3 and len(up_log.starts) == 3,
            "합집합이 좁아졌는데 재시작하지 않았다.",
        )
        assert dep_log.last_start == frozenset({"BTC"})
        assert up_log.last_start == mapped({"BTC"})

        # 재시작을 두 번 겪고도 A의 구독은 그대로다.
        rec_a.clear()
        await rec_a.wait_for(1)
        assert rec_a.symbols == {"BTC"}

    # generator 3개(최초 + 재시작 2회)가 모두 닫히고 스테이지 단위 정리는 한 번씩이다.
    assert dep_log.stopped == 3
    assert up_log.stopped == 3
    assert dep_log.detached == 1
    assert up_log.detached == 1


async def test_dependent_request_api_delivers_mapped_symbols(domain: Domain):
    """`request()`로 소비해도 심볼 변환 파생 스트림이 그대로 동작한다."""

    req = MappedReq(tag="dependent-request")
    received: list[DerivedData] = []

    async with domain.request(req, {"BTC"}) as gen:
        async for data in gen:
            received.append(cast_model(data, DerivedData))
            if len(received) == 3:
                break

    assert {d.symbol for d in received} == {"BTC"}
    with pytest.raises(KeyError):
        domain.get_origin_stage(CounterReq(tag="dependent-request").get_tr_content_id())


# ===== 생성 가드 =====


def test_stage_cannot_be_created_outside_domain():
    """`Stage`는 `Domain`을 통해서만 만들 수 있다."""

    with pytest.raises(TypeError):
        Stage(
            cast(Any, object()),  # 생성 키를 흉내 내도 통과할 수 없다
            id="direct",
            request=CounterReq(tag="direct"),
            output=Recorder(),
        )


async def test_domain_stop_cancels_running_generators(domain: Domain):
    """`stop()`은 도메인이 돌리던 generator 태스크를 모두 취소한다."""

    req = CounterReq(tag="domain-stop")
    log = log_of(req)
    recorder = Recorder()

    stage_cm = domain.stage(req, recorder)
    stage = await stage_cm.__aenter__()
    await stage.update({"BTC"})
    await recorder.wait_for(1)

    await domain.stop()
    await wait_until(lambda: log.stopped == 1, "generator 태스크가 취소되지 않았다.")

    received = recorder.count
    await stage_cm.__aexit__(None, None, None)
    assert recorder.count == received  # 취소 뒤에는 더 이상 오지 않는다
