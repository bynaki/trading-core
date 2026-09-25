"""`routing.py` 명세 — `Channel`, `SymbolRouter`, `PipelineSender`."""

import pytest

from trading_core import Channel, ChannelClosed
from trading_core.routing import PipelineSender, SymbolRouter

from .support.harness import FailingRecorder, Recorder
from .support.streams import CounterData, CounterReq, Relay

# ===== Channel =====


async def test_channel_delivers_the_same_instance():
    """보낸 모델 인스턴스가 그대로 나온다(복사하지 않는다)."""

    channel = Channel()
    data = CounterData(symbol="BTC", count=1)
    await channel.send(data)
    assert await channel.recv() is data


async def test_channel_is_callable_as_sender():
    """`Sender`로 쓰이도록 호출 자체가 `send()`다."""

    channel = Channel()
    await channel(CounterData(symbol="BTC", count=1))
    assert (await channel.recv()).symbol == "BTC"


async def test_channel_reports_closed():
    """닫힌 채널에 접근하면 `ChannelClosed`로 바뀐다."""

    channel = Channel()
    channel._q.shutdown()
    with pytest.raises(ChannelClosed):
        await channel.send(CounterData(symbol="BTC", count=1))
    with pytest.raises(ChannelClosed):
        await channel.recv()


# ===== SymbolRouter =====


async def test_symbol_router_unions_symbols_and_routes_by_symbol():
    """심볼 합집합을 노출하고, 데이터는 그 심볼을 구독한 쪽에만 간다."""

    router = SymbolRouter()
    a, b = Recorder("A"), Recorder("B")
    router.replace(a, {"BTC"})
    router.replace(b, {"BTC", "ETH"})
    assert router.symbols == {"BTC", "ETH"}

    await router(CounterData(symbol="BTC", count=1))
    await router(CounterData(symbol="ETH", count=2))

    assert a.symbols == {"BTC"}
    assert b.symbols == {"BTC", "ETH"}
    assert (a.count, b.count) == (1, 2)


async def test_symbol_router_replaces_previous_registration():
    """같은 `Sender`를 다시 등록하면 심볼이 추가가 아니라 교체된다."""

    router = SymbolRouter()
    recorder = Recorder()
    router.replace(recorder, {"BTC"})
    router.replace(recorder, {"ETH"})
    assert router.symbols == {"ETH"}

    await router(CounterData(symbol="BTC", count=1))
    assert recorder.count == 0


async def test_symbol_router_drops_empty_registration():
    """빈 집합으로 등록하면 구독이 사라진다."""

    router = SymbolRouter()
    recorder = Recorder()
    router.replace(recorder, {"BTC"})
    router.replace(recorder, set())
    assert router.symbols == set()

    await router(CounterData(symbol="BTC", count=1))
    assert recorder.count == 0


async def test_symbol_router_isolates_a_failing_sender():
    """Sender 하나가 던져도 나머지는 받고, 던진 Sender만 빠지며 실패 콜백이 그 심볼로 불린다.

    `TaskGroup`으로 보내면 하나가 던질 때 형제 전송이 취소되고 예외가 라우터를 부른
    공유 generator까지 올라가 모든 소비자가 끊긴다.
    """

    router = SymbolRouter()
    good, bad = Recorder("good"), FailingRecorder("bad")
    failed: list[tuple[set[str], Exception]] = []

    async def on_fail(symbols: set[str], exc: Exception) -> None:
        failed.append((symbols, exc))

    router.replace(good, {"BTC"})
    router.replace(bad, {"BTC", "ETH"}, on_fail)

    await router(CounterData(symbol="BTC", count=1))
    assert good.count == 1
    assert [symbols for symbols, _ in failed] == [{"BTC", "ETH"}]
    assert isinstance(failed[0][1], RuntimeError)
    assert router.symbols == {"BTC"}

    await router(CounterData(symbol="BTC", count=2))
    assert (good.count, bad.count) == (2, 1)


async def test_symbol_router_drain_returns_each_sender_with_its_symbols():
    """`drain()`은 센더마다 (심볼, 실패 콜백)을 돌려주고 라우터를 비운다."""

    router = SymbolRouter()
    a, b = Recorder("A"), Recorder("B")

    async def on_fail(symbols: set[str], exc: Exception) -> None: ...

    router.replace(a, {"BTC"}, on_fail)
    router.replace(b, {"BTC", "ETH"})

    drained = router.drain()
    assert sorted((sorted(symbols), cb is on_fail) for symbols, cb in drained) == [
        (["BTC"], True),
        (["BTC", "ETH"], False),
    ]
    assert router.symbols == set()


# ===== PipelineSender =====


async def test_pipeline_sender_drops_data_for_a_closed_slot():
    """닫힌 슬롯으로 가는 데이터는 조용히 버린다.

    슬롯은 상위 스테이지의 구독이 갱신되기 **전에** 닫힌다. 그 사이 상위가 보낸 데이터가
    `ChannelClosed`로 올라가면 `SymbolRouter`를 거쳐 **공유된 상위 generator가 죽는다.**
    같은 상위 심볼을 다른 소비자가 계속 구독 중이면 합집합이 그대로라 재시작되지 않는다.
    """

    channel = Channel()
    sender = PipelineSender(channel, CounterReq(tag="closed-slot")("BTC/USD") | Relay("BTC"))
    router = SymbolRouter()
    router.replace(sender, {"BTC/USD"})
    channel.shutdown()

    await router(CounterData(symbol="BTC/USD", count=1))  # 예외 없이 버려진다
