"""Tests for the trading-core task/domain orchestration framework.

비동기 테스트는 pytest-asyncio의 auto 모드(pyproject `asyncio_mode = "auto"`)로
실행되므로, `async def` 테스트 함수에 별도 마커를 붙이지 않아도 된다.
"""

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
from trading_core.model import get_model_id, get_origin_name


class Ping(DataModel):
    msg: str = ""


class Pong(DataModel):
    msg: str = ""


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
    async def sender(data: DataModel) -> None:
        pass

    create_stage: Any = Stage

    with pytest.raises(TypeError, match="Domain"):
        create_stage(
            object(),
            id="stage:1",
            request=QuoteReq(),
            output=sender,
        )


def test_shared_sender_accepts_symbol_set() -> None:
    shared = SharedSender()

    async def sender(data: DataModel) -> None:
        pass

    shared.set_sender(sender, {"BTC", "ETH"})

    assert shared.symbols == {"BTC", "ETH"}

    shared.set_sender(sender, set())

    assert shared.symbols == set()


async def test_transmit_queue_raises_closed_connection_after_close() -> None:
    queue = TransmitQueue()
    await queue.close()

    with pytest.raises(ClosedConnection):
        await queue.send(Ping())
    with pytest.raises(ClosedConnection):
        await queue.recv()


async def test_origin_stage_with_no_symbols_is_removed_and_closed() -> None:
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

    async def sender(data: DataModel) -> None:
        pass

    req = EmptyReq()
    domain = Domain()
    async with domain.stage(req, sender) as stage:
        await stage.update(set())

    assert len(contexts) == 1
    assert contexts[0].closed

    async with domain.stage(req, sender) as stage:
        await stage.update(set())

    assert len(contexts) == 2
    assert contexts[1].closed


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
