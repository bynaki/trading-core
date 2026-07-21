"""Tests for the trading-core task/domain orchestration framework.

비동기 테스트는 pytest-asyncio의 auto 모드(pyproject `asyncio_mode = "auto"`)로
실행되므로, `async def` 테스트 함수에 별도 마커를 붙이지 않아도 된다.
"""

from asyncio import Event, Queue, sleep, wait_for
from inspect import CORO_CLOSED, getcoroutinestate
from typing import Any

import pytest

from trading_core import (
    ClosedConnection,
    DataModel,
    DefineError,
    Domain,
    ModelError,
    RequestModel,
    Sequence,
    Stage,
    TransmitQueue,
    generator,
    processor,
    set_origin_name,
    task,
)
from trading_core.domain import SharedSender
from trading_core.helper import TaskManager
from trading_core.model import get_model_id, get_origin_name


class Ping(DataModel):
    msg: str = ""


class Pong(DataModel):
    msg: str = ""


class RecordingSender:
    """Sender 프로토콜을 구현하는 테스트용 출력 수집기."""

    def __init__(self) -> None:
        self.received: list[DataModel] = []
        self.closed = False

    async def __call__(self, data: DataModel) -> None:
        self.received.append(data)

    async def close(self) -> None:
        self.closed = True


def test_datamodel_carries_tr_annotation() -> None:
    """DataModel 인스턴스는 생성 시 자기 출처(annotation)를 들고 다닌다.

    model_name / model_type 등 메타데이터가 자동으로 채워지고,
    DataModel 기본 필드인 symbol 도 정상적으로 설정되는지 확인한다.
    """
    ping = Ping(symbol="BTC", msg="hi")
    ann = ping.get_tr_annotation()
    assert ann["model_name"] == "Ping"
    assert ann["model_type"] == "data"
    assert ping.symbol == "BTC"


def test_model_id_is_stable_per_class() -> None:
    """model_id는 '내용'이 아니라 '클래스 구조'로 결정된다.

    같은 클래스의 인스턴스끼리는 필드 값이 달라도 model_id가 같고,
    클래스 자체와 그 인스턴스도 같은 model_id를 가진다(디스패치 키로 사용됨).
    서로 다른 클래스는 서로 다른 model_id를 가진다.
    """
    assert get_model_id(Ping(msg="a")) == get_model_id(Ping(msg="b"))
    assert get_model_id(Ping) == get_model_id(Ping(msg="a"))
    assert get_model_id(Ping) != get_model_id(Pong)


def test_content_id_tracks_content() -> None:
    """content_id는 반대로 '내용'에 따라 달라진다.

    같은 내용이면 같은 content_id(콘텐츠 해시), 내용이 다르면 다른 값이 나온다.
    내용 기반 중복 제거/캐싱에 쓰일 수 있는 식별자다.
    """
    a = Ping(msg="hello")
    b = Ping(msg="hello")
    c = Ping(msg="world")
    assert a.get_tr_content_id() == b.get_tr_content_id()
    assert a.get_tr_content_id() != c.get_tr_content_id()


class QuoteReq(RequestModel):
    pass


def test_stage_can_only_be_created_by_domain() -> None:
    """Stage를 내부 생성 키 없이 직접 만들 수 없도록 생성 경계를 보호한다."""
    create_stage: Any = Stage

    with pytest.raises(TypeError, match="Domain"):
        create_stage(
            object(),
            id="stage:1",
            request=QuoteReq(),
            output=RecordingSender(),
        )


def test_shared_sender_accepts_symbol_set() -> None:
    """SharedSender가 송신자별 심볼을 등록하고 빈 집합으로 구독을 해제한다."""
    shared = SharedSender()
    sender = RecordingSender()

    shared.set_sender(sender, {"BTC", "ETH"})

    assert shared.symbols == {"BTC", "ETH"}

    shared.set_sender(sender, set())

    assert shared.symbols == set()


async def test_shared_sender_routes_data_and_closes_senders() -> None:
    """SharedSender가 심볼이 맞는 송신자에게 전달하고 종료 시 송신자를 닫는다."""
    shared = SharedSender()
    sender = RecordingSender()
    shared.set_sender(sender, {"BTC"})

    data = Ping(symbol="BTC", msg="hello")
    await shared(data)
    await shared.close()

    assert sender.received == [data]
    assert sender.closed
    assert shared.symbols == set()


async def test_transmit_queue_raises_closed_connection_after_close() -> None:
    """닫힌 TransmitQueue의 송신과 수신 모두 ClosedConnection을 발생시킨다."""
    queue = TransmitQueue()
    await queue.close()

    with pytest.raises(ClosedConnection):
        await queue.send(Ping())
    with pytest.raises(ClosedConnection):
        await queue.recv()


async def test_origin_stage_with_no_symbols_is_removed_and_closed() -> None:
    """구독 심볼이 없는 원천 스테이지는 제거되고 컨텍스트 종료 콜백을 실행한다."""

    class EmptyReq(RequestModel):
        pass

    class Context:
        def __init__(self) -> None:
            self.closed = False

    contexts: list[Context] = []

    @generator(EmptyReq)
    def source(req: EmptyReq) -> Context:
        context = Context()
        contexts.append(context)
        return context

    @source.bind
    async def bind(ctx: Context, symbols: set[str], recv: Any):
        yield Ping()

    @source.close
    async def close(ctx: Context) -> None:
        ctx.closed = True

    req = EmptyReq()
    domain = Domain()
    async with domain.stage(req, RecordingSender()) as stage:
        await stage.update(set())

    assert len(contexts) == 1
    assert contexts[0].closed

    async with domain.stage(req, RecordingSender()) as stage:
        await stage.update(set())

    assert len(contexts) == 2
    assert contexts[1].closed


async def test_missing_required_stage_is_not_created_for_empty_symbols() -> None:
    """요구 심볼이 없으면 불필요한 의존 원천 스테이지를 생성하지 않는다."""

    class RequiredReq(RequestModel):
        pass

    contexts: list[object] = []

    @generator(RequiredReq)
    def source(req: RequiredReq) -> object:
        context = object()
        contexts.append(context)
        return context

    domain = Domain()
    await domain._ensure_require_stage(RequiredReq(), TransmitQueue(), set())

    assert contexts == []


async def test_shared_origin_restarts_only_when_symbol_union_changes() -> None:
    """공유 원천은 전체 구독 심볼의 합집합이 달라질 때만 다시 시작한다."""

    class SharedReq(RequestModel):
        pass

    started = Queue[frozenset[str]]()

    @generator(SharedReq)
    def source(req: SharedReq) -> object:
        return object()

    @source.bind
    async def bind(ctx: object, symbols: set[str], recv: Any):
        started.put_nowait(frozenset(symbols))
        await Event().wait()
        yield Ping()

    domain = Domain()
    await domain.start()

    try:
        async with domain.stage(SharedReq(), RecordingSender()) as first:
            await first.update({"BTC"})
            assert await wait_for(started.get(), 1) == frozenset({"BTC"})

            async with domain.stage(SharedReq(), RecordingSender()) as second:
                await second.update({"BTC"})
                await sleep(0)
                assert started.empty()

                await second.update({"ETH"})
                assert await wait_for(started.get(), 1) == frozenset({"BTC", "ETH"})

            assert await wait_for(started.get(), 1) == frozenset({"BTC"})
    finally:
        await domain.stop()


async def test_completed_origin_does_not_restart_while_subscribers_detach() -> None:
    """완료된 유한 원천은 구독자가 빠져나가는 동안 다시 시작하지 않는다."""

    class FiniteReq(RequestModel):
        pass

    started = Queue[frozenset[str]]()
    ready = Event()
    release_close = Event()
    close_started = Queue[None]()

    class BlockingSender(RecordingSender):
        async def close(self) -> None:
            self.closed = True
            close_started.put_nowait(None)
            await release_close.wait()

    @generator(FiniteReq)
    def source(req: FiniteReq) -> object:
        return object()

    @source.bind
    async def bind(ctx: object, symbols: set[str], recv: Any):
        started.put_nowait(frozenset(symbols))
        await ready.wait()
        yield Ping(symbol=next(iter(symbols)))

    domain = Domain()
    await domain.start()

    try:
        async with domain.stage(FiniteReq(), BlockingSender()) as first:
            await first.update({"BTC"})
            assert await wait_for(started.get(), 1) == frozenset({"BTC"})

            async with domain.stage(FiniteReq(), BlockingSender()) as second:
                await second.update({"ETH"})
                assert await wait_for(started.get(), 1) == frozenset({"BTC", "ETH"})
                ready.set()
                await wait_for(close_started.get(), 1)
                await wait_for(close_started.get(), 1)

            with pytest.raises(TimeoutError):
                await wait_for(started.get(), 0.05)
            release_close.set()
    finally:
        release_close.set()
        await domain.stop()


async def test_task_manager_cancel_pending_releases_name_before_returning() -> None:
    """대기 중 태스크 취소가 이름 점유를 해제하여 같은 이름을 즉시 재사용하게 한다."""

    async def noop() -> None:
        pass

    manager = TaskManager()
    await manager.start()

    try:
        await manager.submit(noop(), "same-name")
        assert await manager.cancel_by_name("same-name")
        await manager.submit(noop(), "same-name")
        assert await manager.cancel_by_name("same-name")
    finally:
        await manager.stop()


async def test_task_manager_closes_coro_cancelled_before_wrapper_starts() -> None:
    """실행 래퍼가 시작되기 전에 취소된 코루틴도 닫혀 자원을 남기지 않는다."""
    started = Event()

    async def target() -> None:
        started.set()

    manager = TaskManager()
    await manager.start()
    coro = target()

    try:
        await manager.submit(coro, "cancel-before-start")
        await sleep(0)

        assert await manager.cancel_by_name("cancel-before-start")
        assert not started.is_set()
        assert getcoroutinestate(coro) == CORO_CLOSED
    finally:
        await manager.stop()


def test_request_model_builds_sequence_with_symbol() -> None:
    """RequestModel 을 symbol로 호출하면 그 심볼에 묶인 Sequence가 만들어진다.

    `QuoteReq()("BTC")` 는 RequestSequence를 반환하며,
    원본 요청 모델과 symbol이 시퀀스에 그대로 보존된다.
    """
    seq = QuoteReq()("BTC")
    assert isinstance(seq, Sequence)
    assert seq.symbol == "BTC"
    assert isinstance(seq.require, QuoteReq)


def test_sequence_composition_preserves_symbol() -> None:
    """`|` 연산자로 Runnable을 이어 붙여도 시퀀스의 symbol은 유지된다.

    파이프라인에 단계(여기서는 task)를 추가해 새 Sequence를 만들어도
    처음 지정한 심볼("ETH")이 끝까지 전달되는지 확인한다.
    """

    class Counter:
        count = 0

    @task(Counter)
    def echo() -> Counter:
        return Counter()

    @echo.on(Ping)
    async def _echo_ping(ctx: Counter, input: Ping) -> Pong:
        return Pong(msg=input.msg)

    seq = QuoteReq()("ETH") | echo()
    assert seq.symbol == "ETH"


async def test_task_invoke_dispatches_to_registered_handler() -> None:
    """task는 입력 모델의 model_id로 등록된 핸들러를 찾아 호출한다.

    Ping 타입에 대해 등록한 핸들러가 실행되어 컨텍스트(Counter)를 변경하고
    Pong 을 반환하는, end-to-end 디스패치 동작을 검증한다.
    """

    class Counter:
        def __init__(self) -> None:
            self.count = 0

    @task(Counter)
    def upper() -> Counter:
        return Counter()

    @upper.on(Ping)
    async def _upper_ping(ctx: Counter, input: Ping) -> Pong:
        ctx.count += 1
        return Pong(msg=input.msg.upper())

    result = await upper().invoke(Ping(msg="hi"))
    assert isinstance(result, Pong)
    assert result.msg == "HI"


async def test_task_invoke_without_handler_returns_none() -> None:
    """등록된 핸들러가 없는 입력을 invoke하면 None이 반환된다.

    task_dict에 매칭되는 콜백이 없을 때 예외 없이 조용히 None을 돌려주는지 확인한다.
    (컨텍스트는 truthy 객체여야 invoke 내부 assert를 통과하므로 빈 클래스 인스턴스를 쓴다.)
    """

    class Ctx:
        pass

    @task(Ctx)
    def empty() -> Ctx:
        return Ctx()

    result = await empty().invoke(Ping(msg="x"))
    assert result is None


def test_domain_rejects_duplicate_registration() -> None:
    """같은 RequestModel 타입으로 domain을 두 번 등록하면 DomainError가 난다.

    DomainModel은 요청 모델의 model_id를 키로 전역 레지스트리에 등록하므로,
    동일 요청 타입의 중복 등록은 막혀야 한다.
    """

    class DupReq(RequestModel):
        pass

    @processor(DupReq)
    def first(req: DupReq) -> DupReq:
        return req

    with pytest.raises(DefineError):

        @processor(DupReq)
        def second(req: DupReq) -> DupReq:
            return req


def test_set_origin_name_rejects_duplicate() -> None:
    """출처 이름(origin name)은 한 번만 지정할 수 있다.

    get_origin_name()으로 출처 이름이 한 번 확정된 뒤에 다시 set_origin_name()을
    호출하면 ModelError가 발생한다. (먼저 get을 호출해 테스트 실행 순서와 무관하게
    '이미 설정된' 상태를 보장한다.)
    """
    get_origin_name()  # ensure an origin name is set
    with pytest.raises(ModelError):
        set_origin_name("anything")
