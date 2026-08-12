"""`domain.py`의 전달 계층 명세 — `TransmitQueue`와 `SharedSender`."""

import pytest

from trading_core import ClosedConnection, TransmitQueue
from trading_core.domain import SharedSender

from .support.harness import Recorder
from .support.streams import CounterData

# ===== TransmitQueue =====


async def test_transmit_queue_delivers_the_same_instance():
    """보낸 모델 인스턴스가 그대로 나온다(복사하지 않는다)."""

    transq = TransmitQueue()
    data = CounterData(symbol="BTC", count=1)
    await transq.send(data)
    assert await transq.recv() is data


async def test_transmit_queue_is_callable_as_sender():
    """`Sender`로 쓰이도록 호출 자체가 `send()`다."""

    transq = TransmitQueue()
    await transq(CounterData(symbol="BTC", count=1))
    assert (await transq.recv()).symbol == "BTC"


async def test_transmit_queue_reports_closed_connection():
    """닫힌 큐에 접근하면 `ClosedConnection`으로 바뀐다."""

    transq = TransmitQueue()
    transq._q.shutdown()
    with pytest.raises(ClosedConnection):
        await transq.send(CounterData(symbol="BTC", count=1))
    with pytest.raises(ClosedConnection):
        await transq.recv()


# ===== SharedSender =====


async def test_shared_sender_unions_symbols_and_routes_by_symbol():
    """심볼 합집합을 노출하고, 데이터는 그 심볼을 구독한 쪽에만 간다."""

    shared = SharedSender()
    a, b = Recorder("A"), Recorder("B")
    shared.set_sender(a, {"BTC"})
    shared.set_sender(b, {"BTC", "ETH"})
    assert shared.symbols == {"BTC", "ETH"}

    await shared(CounterData(symbol="BTC", count=1))
    await shared(CounterData(symbol="ETH", count=2))

    assert a.symbols == {"BTC"}
    assert b.symbols == {"BTC", "ETH"}
    assert (a.count, b.count) == (1, 2)


async def test_shared_sender_replaces_previous_registration():
    """같은 `Sender`를 다시 등록하면 심볼이 추가가 아니라 교체된다."""

    shared = SharedSender()
    recorder = Recorder()
    shared.set_sender(recorder, {"BTC"})
    shared.set_sender(recorder, {"ETH"})
    assert shared.symbols == {"ETH"}

    await shared(CounterData(symbol="BTC", count=1))
    assert recorder.count == 0


async def test_shared_sender_drops_empty_registration():
    """빈 집합으로 등록하면 구독이 사라진다."""

    shared = SharedSender()
    recorder = Recorder()
    shared.set_sender(recorder, {"BTC"})
    shared.set_sender(recorder, set())
    assert shared.symbols == set()

    await shared(CounterData(symbol="BTC", count=1))
    assert recorder.count == 0
