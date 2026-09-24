"""`domain.py` 명세 — content_id 단위 공유, 심볼 합집합, 재시작 조건, 정리 지점.

테스트끼리는 요청의 `tag` 값을 달리해 격리한다. 같은 `tag`는 같은 content_id이고,
곧 같은 공유 스테이지와 같은 기록(`log_of`)을 뜻한다.
"""

from typing import Any, cast

import pytest

from trading_core import Domain, DomainError, Subscription, cast_model, get_model_uid

from .support.harness import BlockingRecorder, Recorder, wait_until
from .support.streams import (
    BEACON_SYMBOL,
    QUOTE_SUFFIX,
    BeaconReq,
    CounterData,
    CounterReq,
    DerivedData,
    DerivedReq,
    MappedReq,
    SplitReq,
    SwingData,
    SwingReq,
    UnboundReq,
    log_of,
    split_upstream,
)


def shared_symbols(domain: Domain, req: CounterReq | DerivedReq | MappedReq) -> set[str]:
    """요청의 공유 스테이지가 현재 들고 있는 심볼 합집합. 공유 중이 아니면 빈 집합이다."""

    return domain.get_shared_symbols(req.tr_content_id)


def mapped(symbols: set[str]) -> frozenset[str]:
    """`MappedReq`의 require가 하위 심볼을 바꿔 상위에 올리는 표기."""

    return frozenset(f"{s}{QUOTE_SUFFIX}" for s in symbols)


# ===== Domain.stream() =====


async def test_stream_delivers_data_and_cleans_up(domain: Domain):
    """`stream()`은 구독한 심볼의 데이터만 주고, 빠져나오면 스테이지를 정리한다."""

    req = CounterReq(tag="request-basic")
    log = log_of(req)
    received: list[CounterData] = []

    async with domain.stream(req, {"BTC", "ETH"}) as gen:
        async for data in gen:
            received.append(cast_model(data, CounterData))
            if len(received) == 4:
                break

    assert {d.symbol for d in received} == {"BTC", "ETH"}
    assert log.inits == 1
    assert log.starts == [frozenset({"BTC", "ETH"})]
    assert log.stopped == 1  # 업데이트 단위 정리(generator의 finally)
    assert log.detached == 1  # 스테이지 단위 정리
    assert domain.get_shared_symbols(req.tr_content_id) == set()


async def test_stream_without_binder_raises_domain_error(domain: Domain):
    """binder가 없는 요청은 `DomainError`."""

    # 스테이지는 첫 소비 시점에 만들어지므로 그때 예외가 난다.
    with pytest.raises(DomainError):
        async with domain.stream(UnboundReq(tag="none"), {"BTC"}) as gen:
            async for _ in gen:
                break


# ===== content_id 단위 공유 =====


async def test_equal_requests_share_one_stage(domain: Domain):
    """필드 값이 같은 요청은 인스턴스가 달라도 하나의 원천 스테이지를 공유한다."""

    tag = "shared-origin"
    req_a, req_b = CounterReq(tag=tag), CounterReq(tag=tag)
    assert get_model_uid(req_a) != get_model_uid(req_b)
    assert req_a.tr_content_id == req_b.tr_content_id
    log = log_of(req_a)
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.subscribe(req_a, rec_a) as sub_a, domain.subscribe(req_b, rec_b) as sub_b:
        await sub_a.update({"BTC"})
        await sub_b.update({"ETH"})
        assert shared_symbols(domain, req_a) == shared_symbols(domain, req_b) == {"BTC", "ETH"}
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

    async with domain.subscribe(req_a, rec_a) as sub_a, domain.subscribe(req_b, rec_b) as sub_b:
        await sub_a.update({"BTC"})
        await sub_b.update({"BTC"})
        assert shared_symbols(domain, req_a) == {"BTC"}
        assert shared_symbols(domain, req_b) == {"BTC"}
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

    async with domain.subscribe(req, rec_a) as sub_a:
        await sub_a.update({"BTC", "ETH"})
        await rec_a.wait_for(1)
        assert log.starts == [frozenset({"BTC", "ETH"})]

        async with domain.subscribe(req, rec_b) as sub_b:
            # 이미 합집합에 있는 심볼만 구독하면 합집합이 그대로라 재시작하지 않는다.
            await sub_b.update({"BTC"})
            await rec_b.wait_for(1)
            assert rec_b.symbols == {"BTC"}
            assert log.starts == [frozenset({"BTC", "ETH"})]

            # 합집합이 넓어지면 재시작한다.
            await sub_b.update({"BTC", "SOL"})
            assert shared_symbols(domain, req) == {"BTC", "ETH", "SOL"}
            await wait_until(lambda: len(log.starts) == 2, "합집합이 넓어졌는데 재시작하지 않았다.")
            assert log.last_start == frozenset({"BTC", "ETH", "SOL"})

        # 구독이 빠져도 합집합이 달라지므로 재시작한다.
        assert shared_symbols(domain, req) == {"BTC", "ETH"}
        await wait_until(lambda: len(log.starts) == 3, "구독이 빠졌는데 재시작하지 않았다.")
        assert log.last_start == frozenset({"BTC", "ETH"})

    assert log.stopped == 3  # 재시작 2번 + 마지막 정리 1번
    assert log.detached == 1


async def test_update_replaces_symbols_and_empty_set_unsubscribes(domain: Domain):
    """`update()`는 추가가 아니라 교체이고, 빈 집합은 구독 해제다."""

    req = CounterReq(tag="update-replace")
    log = log_of(req)
    recorder = Recorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC"})
        assert shared_symbols(domain, req) == {"BTC"}

        await sub.update({"ETH"})
        assert shared_symbols(domain, req) == {"ETH"}

        await sub.update(set())
        assert domain.get_shared_symbols(req.tr_content_id) == set()
        assert log.detached == 1


async def test_stage_symbols_are_always_contained_in_the_origin_union(domain: Domain):
    """각 스테이지의 심볼은 언제나 원천 합집합에 포함된다."""

    req = CounterReq(tag="containment")
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.subscribe(req, rec_a) as sub_a, domain.subscribe(req, rec_b) as sub_b:
        symbols_a: set[str] = set()
        symbols_b: set[str] = set()
        for i in range(3):
            symbols_a.add(f"A-{i}")
            symbols_b.add(f"B-{i}")
            await sub_a.update(symbols_a)
            await sub_b.update(symbols_b)
            union = shared_symbols(domain, req)
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

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC"})
        await recorder.wait_for(2)
        assert shared_symbols(domain, upstream) == {"BTC"}
        assert up_log.starts == [frozenset({"BTC"})]
        assert {d.symbol for d in recorder.received} == {"BTC"}
        assert isinstance(recorder.received[0], DerivedData)

    assert dep_log.detached == 1
    assert up_log.detached == 1
    assert domain.get_shared_symbols(req.tr_content_id) == set()
    assert domain.get_shared_symbols(upstream.tr_content_id) == set()


async def test_dependent_stages_with_same_upstream_share_it(domain: Domain):
    """상위 요청의 content_id가 같으면 파생 스테이지가 달라도 원천을 공유한다."""

    tag = "dependent-shared-upstream"
    upstream = CounterReq(tag=tag)
    derived_req, mapped_req = DerivedReq(tag=tag), MappedReq(tag=tag)
    rec_derived, rec_mapped = Recorder("derived"), Recorder("mapped")

    async with (
        domain.subscribe(derived_req, rec_derived) as sub_derived,
        domain.subscribe(mapped_req, rec_mapped) as sub_mapped,
    ):
        await sub_derived.update({"BTC/USD"})  # 변환 없이 상위 표기를 그대로 구독한다
        await sub_mapped.update({"ETH"})  # 변환되어 "ETH/USD"로 올라간다
        assert shared_symbols(domain, upstream) == {"BTC/USD", "ETH/USD"}
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

    async with domain.subscribe(req, rec_a) as sub_a:
        await sub_a.update({"BTC"})
        await rec_a.wait_for(1)
        assert up_log.last_start == frozenset({f"BTC{QUOTE_SUFFIX}"})

        async with domain.subscribe(req, rec_b) as sub_b:
            await sub_b.update({"ETH"})
            # 상위에는 A와 B의 합집합이 올라가야 한다.
            upstream_union = {f"BTC{QUOTE_SUFFIX}", f"ETH{QUOTE_SUFFIX}"}
            assert shared_symbols(domain, upstream) == upstream_union
            await wait_until(
                lambda: up_log.last_start == frozenset(upstream_union),
                "상위 generator가 합집합으로 재시작하지 않았다.",
            )

            # B가 붙은 뒤에도 A는 계속 데이터를 받는다.
            rec_a.clear()
            await rec_a.wait_for(1)
            await rec_b.wait_for(1)

        # B가 떠나면 상위 구독도 A의 몫만 남는다.
        assert shared_symbols(domain, upstream) == {f"BTC{QUOTE_SUFFIX}"}
        rec_a.clear()
        await rec_a.wait_for(1)

    assert rec_a.symbols == {"BTC"}
    assert rec_b.symbols == {"ETH"}


async def test_dependent_restarts_only_when_the_union_changes(domain: Domain):
    """파생 스테이지도 심볼 합집합이 실제로 달라질 때만 재시작한다.

    `test_origin_restarts_only_when_the_union_changes`와 같은 규칙을 파생 분기에서
    확인한다. 파생 쪽은 상위 원천까지 함께 움직이므로 두 계층의 기록을 나란히 본다.

    새 구독자가 데이터를 받는지도 함께 단정한다. 조기 반환이 `replace()` **뒤에**
    있어야 재시작 없이도 구독자 목록에 들어가기 때문이다. 순서가 뒤바뀌면 재시작
    횟수는 그대로면서 새 구독자만 다음 재시작까지 굶는다. (ex06과 같은 시나리오다.)
    """

    tag = "dependent-union-restart"
    req = MappedReq(tag=tag)
    upstream = CounterReq(tag=tag)
    dep_log, up_log = log_of(req), log_of(upstream)
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.subscribe(req, rec_a) as sub_a:
        await sub_a.update({"BTC"})
        await rec_a.wait_for(1)
        assert dep_log.starts == [frozenset({"BTC"})]
        assert up_log.starts == [mapped({"BTC"})]

        async with domain.subscribe(req, rec_b) as sub_b:
            # 이미 합집합에 있는 심볼이므로 두 계층 모두 재시작하지 않아야 한다.
            await sub_b.update({"BTC"})
            await rec_b.wait_for(1)
            assert rec_b.symbols == {"BTC"}
            assert shared_symbols(domain, req) == {"BTC"}
            assert shared_symbols(domain, upstream) == set(mapped({"BTC"}))
            assert len(dep_log.starts) == 1
            assert len(up_log.starts) == 1
            # 재시작이 없었으니 기존 generator의 finally도 아직 돌지 않았다.
            assert dep_log.stopped == 0
            assert up_log.stopped == 0

            # 합집합이 넓어지면 두 계층이 함께 재시작한다.
            await sub_b.update({"BTC", "ETH"})
            assert shared_symbols(domain, req) == {"BTC", "ETH"}
            assert shared_symbols(domain, upstream) == set(mapped({"BTC", "ETH"}))
            await wait_until(
                lambda: len(dep_log.starts) == 2 and len(up_log.starts) == 2,
                "합집합이 넓어졌는데 재시작하지 않았다.",
            )
            assert dep_log.last_start == frozenset({"BTC", "ETH"})
            assert up_log.last_start == mapped({"BTC", "ETH"})

        # B가 떠나 합집합이 좁아져도 재시작한다.
        assert shared_symbols(domain, req) == {"BTC"}
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


async def test_dependent_stream_delivers_mapped_symbols(domain: Domain):
    """`stream()`으로 소비해도 심볼 변환 파생 스트림이 그대로 동작한다."""

    req = MappedReq(tag="dependent-request")
    received: list[DerivedData] = []

    async with domain.stream(req, {"BTC"}) as gen:
        async for data in gen:
            received.append(cast_model(data, DerivedData))
            if len(received) == 3:
                break

    assert {d.symbol for d in received} == {"BTC"}
    assert domain.get_shared_symbols(CounterReq(tag="dependent-request").tr_content_id) == set()


# ===== 세션 스트림 =====


async def test_session_stage_maps_symbols_to_the_upstream(domain: Domain):
    """세션 스테이지가 상위에 올리는 심볼은 **파이프라인이 요구한 상위 표기**다.

    소비자가 구독한 하위 심볼(`BTC`)을 그대로 상위에 올리면 안 된다. 상·하위 표기가
    같은 요청이면 이 회귀가 드러나지 않으므로, 여기서는 일부러 표기가 다른
    `SwingReq`(`BTC` → `BTC/USD`)를 쓴다.
    """

    tag = "session-mapping"
    req = SwingReq(tag=tag)
    upstream = CounterReq(tag=tag)
    up_log = log_of(upstream)
    recorder = Recorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC"})
        assert shared_symbols(domain, upstream) == {f"BTC{QUOTE_SUFFIX}"}
        await recorder.wait_for(2)

    assert up_log.last_start == frozenset({f"BTC{QUOTE_SUFFIX}"})
    assert recorder.symbols == {"BTC"}  # 소비자는 하위 표기로 받는다
    assert isinstance(recorder.received[0], SwingData)


async def test_session_stage_cleans_up_the_upstream(domain: Domain):
    """세션 스테이지를 빠져나오면 그것이 만든 상위 원천도 함께 정리된다."""

    tag = "session-cleanup"
    req = SwingReq(tag=tag)
    upstream = CounterReq(tag=tag)
    log, up_log = log_of(req), log_of(upstream)
    recorder = Recorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC"})
        await recorder.wait_for(1)

    assert log.detached == 1
    assert up_log.detached == 1
    assert domain.get_shared_symbols(upstream.tr_content_id) == set()


async def test_session_always_subscribes_alongside_symbols(domain: Domain):
    """always 파이프라인은 구독 심볼과 **나란히** 상위에 올라간다.

    always는 `"__always__"`라는 센티널 슬롯을 쓴다. 이 센티널이 실제 심볼로 새면
    binder가 `"__always__"`를 심볼인 양 받고 같은 이름의 태스크가 두 번 제출된다.
    """

    tag = "session-always"
    req = BeaconReq(tag=tag)
    upstream = CounterReq(tag=tag)
    recorder = Recorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC"})
        assert shared_symbols(domain, upstream) == {f"BTC{QUOTE_SUFFIX}", BEACON_SYMBOL}
        await recorder.wait_for(2)

    assert recorder.symbols == {"BTC", BEACON_SYMBOL}


async def test_session_detach_unbinds_remaining_symbols(domain: Domain):
    """스테이지를 빠져나올 때 남아 있던 심볼도 `unbind`로 닫힌다.

    `update()`로 심볼이 빠지는 경로만 `unbind`를 부르고 `detach()`는 부르지 않으면,
    심볼을 들고 종료하는 보통의 경우에 심볼별 자원이 샌다.
    """

    tag = "session-detach-unbind"
    req = SwingReq(tag=tag)
    log = log_of(req)
    recorder = Recorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC", "ETH"})
        await recorder.wait_for(2)

    assert sorted(log.unbound) == ["BTC", "ETH"]
    assert log.detached == 1


async def test_session_unbinds_each_symbol_exactly_once(domain: Domain):
    """`bind`한 심볼은 어느 정리 경로로 닫히든 `unbind`가 정확히 한 번이다."""

    tag = "session-unbind-once"
    req = SwingReq(tag=tag)
    log = log_of(req)
    recorder = Recorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC", "ETH"})
        await recorder.wait_for(2)

        await sub.update({"ETH"})  # BTC만 빠진다
        assert log.unbound == ["BTC"]

    # 남아 있던 ETH가 종료 시점에 닫히고, 이미 닫힌 BTC가 또 닫히지는 않는다.
    assert sorted(log.unbound) == ["BTC", "ETH"]


async def test_session_symbol_can_be_resubscribed_right_away(domain: Domain):
    """뺀 심볼을 곧바로 다시 넣어도 슬롯이 새로 열린다.

    슬롯 태스크 이름은 `{stage_id}:{symbol}`이다. 슬롯을 닫을 때 큐만 닫고 태스크가 끝나기를
    기다리지 않으면, 소비자가 느려 태스크가 전송에 묶여 있는 동안 이름이 점유된 채
    남아 같은 심볼의 재구독이 `TaskManagerError`로 실패한다.
    """

    tag = "session-resubscribe"
    req = SwingReq(tag=tag)
    log = log_of(req)
    recorder = BlockingRecorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC"})
        await recorder.wait_for(1)  # 슬롯 태스크가 전송에 묶였다

        await sub.update(set())
        await sub.update({"BTC"})  # 옛 슬롯 태스크의 이름이 남아 있으면 여기서 실패한다
        recorder.release()
        recorder.clear()
        await recorder.wait_for(1)

    assert recorder.symbols == {"BTC"}
    assert log.unbound == ["BTC", "BTC"]


async def test_session_always_slot_is_not_unbound(domain: Domain):
    """always 슬롯은 `bind`된 적이 없으므로 `unbind`도 하지 않는다."""

    tag = "session-always-unbind"
    req = BeaconReq(tag=tag)
    log = log_of(req)
    recorder = Recorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC"})
        await recorder.wait_for(2)

    assert log.unbound == ["BTC"]


async def test_session_detaches_an_upstream_no_pipeline_uses(domain: Domain):
    """어떤 파이프라인도 쓰지 않게 된 상위 스테이지는 그 자리에서 떼어 내고 다시 건드리지 않는다.

    떼어 내지 않고 남겨 두면 이후 `update()`마다 빈 심볼 집합으로 갱신되는데, 원천이
    이미 사라진 상위는 그때마다 새 원천이 만들어졌다가(init) 곧바로 정리된다(detach).
    """

    tag = "session-split"
    req = SplitReq(tag=tag)
    btc_log = log_of(split_upstream(tag, "BTC"))
    recorder = Recorder()

    async with domain.subscribe(req, recorder) as sub:
        await sub.update({"BTC", "ETH"})
        await wait_until(lambda: recorder.symbols == {"BTC", "ETH"})

        await sub.update({"ETH"})  # BTC만 쓰던 상위가 쓰이지 않게 된다
        assert (btc_log.inits, btc_log.detached) == (1, 1)

        await sub.update({"ETH", "XRP"})  # BTC와 무관한 갱신
        await sub.update({"ETH"})
        assert (btc_log.inits, btc_log.detached) == (1, 1)

    assert (btc_log.inits, btc_log.detached) == (1, 1)


async def test_equal_session_requests_do_not_share_a_stage(domain: Domain):
    """내용이 같은 세션 요청은 **공유되지 않는다** — content_id가 같아도 별개다.

    원천·파생은 content_id 단위로 스테이지와 컨텍스트를 공유하지만
    (`test_equal_requests_share_one_stage`), `_create_session_subscription()`는
    `_shared_stages`를 보지도 채우지도 않는다. 요청마다 스테이지가 생기고 init
    콜백이 다시 불린다. 공유의 경계는 그 아래 상위 원천에 있다.
    """

    tag = "session-no-share"
    req_a, req_b = SwingReq(tag=tag), SwingReq(tag=tag)
    assert get_model_uid(req_a) != get_model_uid(req_b)
    assert req_a.tr_content_id == req_b.tr_content_id
    upstream = CounterReq(tag=tag)
    log, up_log = log_of(req_a), log_of(upstream)  # content_id가 같으니 기록은 하나로 모인다
    rec_a, rec_b = Recorder("A"), Recorder("B")

    async with domain.subscribe(req_a, rec_a) as sub_a, domain.subscribe(req_b, rec_b) as sub_b:
        await sub_a.update({"BTC"})
        await sub_b.update({"BTC"})  # 같은 심볼이어도 슬롯은 스테이지마다 따로 열린다
        # 세션 요청은 공유되지 않는다. 공개 API는 "공유 안 됨"과 "공유되지만 심볼 없음"이 둘 다
        # 빈 집합이라, 공유 레지스트리에 아예 들어가지 않는지는 내부를 직접 본다.
        assert domain.get_shared_symbols(req_a.tr_content_id) == set()
        assert req_a.tr_content_id not in domain._shared_stages
        assert log.inits == 2  # 요청마다 컨텍스트가 새로 만들어진다
        assert up_log.inits == 1  # 상위 원천은 여전히 하나를 공유한다
        assert shared_symbols(domain, upstream) == {f"BTC{QUOTE_SUFFIX}"}
        await rec_a.wait_for(2)
        await rec_b.wait_for(2)

    # 두 소비자가 같은 상위 generator의 출력을 각자의 슬롯으로 받는다.
    assert rec_a.symbols == {"BTC"}
    assert rec_b.symbols == {"BTC"}
    # 합집합이 그대로이므로 두 번째 구독이 상위를 재시작시키지 않는다.
    assert up_log.starts == [frozenset({f"BTC{QUOTE_SUFFIX}"})]
    # 슬롯도 컨텍스트도 스테이지 소유이므로 정리도 스테이지마다 한 번씩이다.
    assert log.unbound == ["BTC", "BTC"]
    assert log.detached == 2
    assert up_log.detached == 1


# ===== 생성 가드 =====


def test_subscription_cannot_be_created_outside_domain():
    """`Subscription`은 `Domain`을 통해서만 만들 수 있다."""

    with pytest.raises(TypeError):
        Subscription(
            cast(Any, object()),  # 생성 키를 흉내 내도 통과할 수 없다
            id="direct",
            request=CounterReq(tag="direct"),
            sender=Recorder(),
        )


async def test_domain_stop_cancels_running_generators(domain: Domain):
    """`stop()`은 도메인이 돌리던 generator 태스크를 모두 취소한다."""

    req = CounterReq(tag="domain-stop")
    log = log_of(req)
    recorder = Recorder()

    sub_cm = domain.subscribe(req, recorder)
    sub = await sub_cm.__aenter__()
    await sub.update({"BTC"})
    await recorder.wait_for(1)

    await domain.stop()
    await wait_until(lambda: log.stopped == 1, "generator 태스크가 취소되지 않았다.")

    received = recorder.count
    await sub_cm.__aexit__(None, None, None)
    assert recorder.count == received  # 취소 뒤에는 더 이상 오지 않는다
