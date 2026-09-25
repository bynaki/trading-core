"""도메인 테스트가 공유하는 요청·데이터 모델과 binder 정의.

`BindPack._registry`는 프로세스 전역이라 **요청 타입 하나당 등록은 한 번뿐**이다.
그래서 binder는 이 모듈에서 import 시점에 한 번만 정의하고, 테스트끼리는 `tag` 필드
값을 달리해 서로 다른 content_id(=서로 다른 원천 스테이지)를 쓰는 방식으로 격리한다.
같은 `tag`를 쓰는 두 테스트는 스테이지와 기록을 공유하게 되므로 주의할 것.

각 binder는 자기 스테이지에서 일어난 일을 `StreamLog`에 기록한다. generator가 언제
몇 번 (재)시작했는지, 어떤 심볼 합집합으로 시작했는지, 정리 콜백이 몇 번 불렸는지가
도메인 불변식 검증의 재료다.
"""

from asyncio import sleep
from collections import defaultdict
from dataclasses import dataclass, field

from trading_core import (
    DataModel,
    DerivedRequest,
    Receiver,
    Runnable,
    SessionRequest,
    SourceRequest,
    cast_model,
    initialize,
)
from trading_core.model import BaseRequest

EMIT_INTERVAL = 0.01
"""테스트용 발행 간격. 예제(0.5초)보다 훨씬 짧게 잡아 테스트를 빠르게 끝낸다."""

QUOTE_SUFFIX = "/USD"
"""`MappedReq`가 하위 심볼을 상위 표기로 바꿀 때 붙이는 접미사."""


@dataclass
class StreamLog:
    """한 스테이지(content_id)에서 일어난 수명 주기 사건 기록."""

    inits: int = 0
    """init 콜백이 불린 횟수. content_id 단위 공유가 깨지면 2 이상이 된다."""

    starts: list[frozenset[str]] = field(default_factory=list)
    """generate 콜백이 (재)시작할 때마다 받은 심볼 합집합."""

    stopped: int = 0
    """generator의 `finally`가 실행된 횟수(업데이트 단위 정리)."""

    detached: int = 0
    """detach 콜백이 불린 횟수(스테이지 단위 정리)."""

    unbound: list[str] = field(default_factory=list)
    """unbind 콜백이 닫은 심볼. 이중 호출이 잡히도록 집합이 아니라 목록이다."""

    @property
    def last_start(self) -> frozenset[str]:
        """가장 최근 (재)시작이 받은 심볼 합집합."""

        return self.starts[-1]


_logs: defaultdict[str, StreamLog] = defaultdict(StreamLog)


def log_of(req: BaseRequest) -> StreamLog:
    """요청의 content_id에 대응하는 기록을 돌려준다."""

    return _logs[req.tr_content_id]


class StreamContext:
    """init 콜백이 만들어 스테이지 수명 동안 공유되는 컨텍스트."""

    def __init__(self, req: BaseRequest) -> None:
        self.req = req
        self.log = log_of(req)
        self.log.inits += 1


# ===== 원천 제너레이터 =====


class CounterReq(SourceRequest):
    """`tag`로 원천 스테이지를 구분하는 카운트 요청."""

    tag: str


class CounterData(DataModel):
    """한 바퀴마다 1씩 늘어나는 카운트."""

    count: int


@initialize
def counter(req: CounterReq) -> StreamContext:
    """카운트 원천의 공유 컨텍스트를 만든다."""

    return StreamContext(req)


@counter
async def _(ctx: StreamContext, symbols: set[str]):
    """구독 심볼 전체를 한 바퀴씩 돌며 카운트를 발행한다."""

    ctx.log.starts.append(frozenset(symbols))
    ordered = sorted(symbols)
    count = 0
    try:
        while True:
            for symbol in ordered:
                yield CounterData(symbol=symbol, count=count)
            count += 1
            await sleep(EMIT_INTERVAL)
    finally:
        ctx.log.stopped += 1


@counter.detached
async def _(ctx: StreamContext):
    """마지막 구독이 사라질 때 호출된다."""

    ctx.log.detached += 1


# ===== 심볼을 그대로 중계하는 파생 제너레이터 =====


class DerivedReq(DerivedRequest):
    """같은 `tag`의 `CounterReq`를 상위로 요구하는 파생 요청."""

    tag: str


@DerivedReq.require
def _(req: DerivedReq) -> CounterReq:
    """심볼과 무관하게 상위 요청만 돌려주는 `RequireCb` 형태."""

    return CounterReq(tag=req.tag)


class DerivedData(DataModel):
    """상위 카운트를 그대로 옮겨 담은 파생 출력."""

    count: int


@initialize
def derived(req: DerivedReq) -> StreamContext:
    """파생 스테이지의 공유 컨텍스트를 만든다."""

    return StreamContext(req)


@derived
async def _(ctx: StreamContext, symbols: set[str], recv: Receiver):
    """상위 데이터를 받아 구독 중인 심볼만 흘려보낸다."""

    ctx.log.starts.append(frozenset(symbols))
    try:
        while True:
            data = cast_model(await recv(), CounterData)
            if data.symbol in symbols:
                yield DerivedData(symbol=data.symbol, count=data.count)
    finally:
        ctx.log.stopped += 1


@derived.detached
async def _(ctx: StreamContext):
    """마지막 파생 구독이 사라질 때 호출된다."""

    ctx.log.detached += 1


# ===== 심볼까지 변환하는 파생 제너레이터 =====


class MappedReq(DerivedRequest):
    """하위 심볼(`BTC`)을 상위 표기(`BTC/USD`)로 바꿔 요구하는 파생 요청."""

    tag: str


@MappedReq.require
def _(req: MappedReq, symbols: set[str]) -> tuple[CounterReq, set[str]]:
    """상위 요청과 함께 변환한 심볼 집합을 돌려주는 `RequireCbWithSym` 형태."""

    return CounterReq(tag=req.tag), {f"{s}{QUOTE_SUFFIX}" for s in symbols}


@initialize
def mapped(req: MappedReq) -> StreamContext:
    """심볼 변환 파생 스테이지의 공유 컨텍스트를 만든다."""

    return StreamContext(req)


@mapped
async def _(ctx: StreamContext, symbols: set[str], recv: Receiver):
    """상위 표기를 기초 자산으로 되돌려 발행한다."""

    ctx.log.starts.append(frozenset(symbols))
    try:
        while True:
            data = cast_model(await recv(), CounterData)
            symbol = data.symbol.removesuffix(QUOTE_SUFFIX)
            if symbol in symbols:
                yield DerivedData(symbol=symbol, count=data.count)
    finally:
        ctx.log.stopped += 1


@mapped.detached
async def _(ctx: StreamContext):
    """마지막 파생 구독이 사라질 때 호출된다."""

    ctx.log.detached += 1


# ===== 세션(SessionRequest) 스트림 =====
#
# `SessionRequest`는 심볼마다 `Pipeline`을 만들어 상위 원천에 붙이는 요청이다. 상위에
# 등록되는 심볼은 파이프라인이 요구한 표기(`BTC/USD`)이고 소비자가 받는 심볼은 하위
# 표기(`BTC`)다. 이 둘을 **일부러 다르게** 두어야 상·하위를 뒤바꾼 회귀가 드러난다.


class SwingReq(SessionRequest):
    """하위 `BTC`를 상위 `BTC/USD`로 바꿔 요구하는 세션 요청."""

    tag: str


class SwingData(DataModel):
    """상위 카운트를 하위 표기로 옮겨 담은 출력."""

    count: int


class Relay(Runnable):
    """상위 `CounterData`를 하위 표기의 `SwingData`로 옮긴다."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def invoke(self, input: CounterData) -> SwingData | None:
        return SwingData(symbol=self.symbol, count=input.count)


@initialize
def swing(req: SwingReq) -> StreamContext:
    """세션 스테이지의 컨텍스트를 만든다."""

    return StreamContext(req)


@swing
async def _(ctx: StreamContext, symbol: str):
    """심볼 하나를 상위 표기로 바꿔 구독하는 파이프라인을 낸다."""

    tag = cast_model(ctx.req, SwingReq).tag
    yield CounterReq(tag=tag)(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


@swing.unbind
async def _(ctx: StreamContext, symbol: str):
    """심볼 하나의 구독이 닫힐 때 호출된다."""

    ctx.log.unbound.append(symbol)


@swing.detached
async def _(ctx: StreamContext):
    """마지막 구독이 사라질 때 호출된다."""

    ctx.log.detached += 1


# ===== always까지 쓰는 세션 스트림 =====

BEACON_SYMBOL = "BEACON/USD"
"""`BeaconReq`가 구독 심볼과 무관하게 항상 상위에 올리는 심볼."""


class BeaconReq(SessionRequest):
    """구독 심볼과 별개로 상위 심볼 하나를 늘 요구하는 세션 요청."""

    tag: str


@initialize
def beacon(req: BeaconReq) -> StreamContext:
    """always를 쓰는 세션 스테이지의 컨텍스트를 만든다."""

    return StreamContext(req)


@beacon
async def _(ctx: StreamContext, symbol: str):
    """`SwingReq`와 같은 방식으로 심볼별 파이프라인을 낸다."""

    tag = cast_model(ctx.req, BeaconReq).tag
    yield CounterReq(tag=tag)(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


@beacon.always
async def _(ctx: StreamContext):
    """구독 심볼이 무엇이든 항상 붙는 파이프라인."""

    tag = cast_model(ctx.req, BeaconReq).tag
    yield CounterReq(tag=tag)(BEACON_SYMBOL) | Relay(BEACON_SYMBOL)


@beacon.unbind
async def _(ctx: StreamContext, symbol: str):
    """심볼 하나의 구독이 닫힐 때 호출된다."""

    ctx.log.unbound.append(symbol)


# ===== 심볼마다 다른 상위를 드는 세션 스트림 =====


class SplitReq(SessionRequest):
    """심볼마다 **서로 다른** 상위 요청(`split_upstream()`)에 붙는 세션 요청.

    심볼 하나가 빠지면 그 심볼만 쓰던 상위 요청이 통째로 쓰이지 않게 된다.
    """

    tag: str


def split_upstream(tag: str, symbol: str) -> CounterReq:
    """`SplitReq`의 심볼 `symbol`이 붙는 상위 요청."""

    return CounterReq(tag=f"{tag}:{symbol}")


@initialize
def split(req: SplitReq) -> StreamContext:
    """심볼별 상위를 쓰는 세션 스테이지의 컨텍스트를 만든다."""

    return StreamContext(req)


@split
async def _(ctx: StreamContext, symbol: str):
    """심볼마다 전용 상위 요청을 구독하는 파이프라인을 낸다."""

    tag = cast_model(ctx.req, SplitReq).tag
    yield split_upstream(tag, symbol)(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


# ===== 실패를 주입하는 스트림 =====
#
# 코어는 재시도하지 않고 실패를 `StageFailed`로 알린다. 아래 binder는 그 경로를 시험하려고
# 일부러 던진다. 원천이 던지는 시점은 `trip()`으로 정해 경합 없이 재현한다.


class InjectedFailure(RuntimeError):
    """테스트 binder가 일부러 던지는 예외."""


_tripped: set[str] = set()


def trip(tag: str) -> None:
    """`tag`의 `FlakyReq` 원천이 다음 바퀴에 한 번 던지게 한다."""

    _tripped.add(tag)


class FlakyReq(SourceRequest):
    """`trip(tag)`되면 한 번 던지는 원천 요청. 그 전까지는 `CounterReq`처럼 발행한다."""

    tag: str
    detach_raises: bool = False


@initialize
def flaky(req: FlakyReq) -> StreamContext:
    """끊기는 원천의 공유 컨텍스트를 만든다."""

    return StreamContext(req)


@flaky
async def _(ctx: StreamContext, symbols: set[str]):
    """카운트를 발행하다가 `trip()`되면 던진다."""

    tag = cast_model(ctx.req, FlakyReq).tag
    ctx.log.starts.append(frozenset(symbols))
    count = 0
    try:
        while True:
            if tag in _tripped:
                _tripped.discard(tag)
                raise InjectedFailure(f"원천이 끊겼다. - {tag}")
            for symbol in sorted(symbols):
                yield CounterData(symbol=symbol, count=count)
            count += 1
            await sleep(EMIT_INTERVAL)
    finally:
        ctx.log.stopped += 1


@flaky.detached
async def _(ctx: StreamContext):
    """마지막 구독이 사라지거나 스테이지가 실패할 때 호출된다. 설정에 따라 던진다."""

    ctx.log.detached += 1
    if cast_model(ctx.req, FlakyReq).detach_raises:
        raise InjectedFailure("detach 콜백이 실패했다.")


class FlakyDerivedReq(DerivedRequest):
    """같은 `tag`의 `FlakyReq`를 상위로 요구하는 파생 요청."""

    tag: str


@FlakyDerivedReq.require
def _(req: FlakyDerivedReq) -> FlakyReq:
    return FlakyReq(tag=req.tag)


@initialize
def flaky_derived(req: FlakyDerivedReq) -> StreamContext:
    """끊기는 원천 위의 파생 스테이지 컨텍스트를 만든다."""

    return StreamContext(req)


@flaky_derived
async def _(ctx: StreamContext, symbols: set[str], recv: Receiver):
    """상위 데이터를 받아 구독 중인 심볼만 흘려보낸다."""

    ctx.log.starts.append(frozenset(symbols))
    try:
        while True:
            data = cast_model(await recv(), CounterData)
            if data.symbol in symbols:
                yield DerivedData(symbol=data.symbol, count=data.count)
    finally:
        ctx.log.stopped += 1


@flaky_derived.detached
async def _(ctx: StreamContext):
    ctx.log.detached += 1


class BrokenDerivedReq(DerivedRequest):
    """상위 데이터를 받자마자 던지는 파생 요청. 상위는 같은 `tag`의 `CounterReq`다."""

    tag: str


@BrokenDerivedReq.require
def _(req: BrokenDerivedReq) -> CounterReq:
    return CounterReq(tag=req.tag)


@initialize
def broken_derived(req: BrokenDerivedReq) -> StreamContext:
    """계산이 실패하는 파생 스테이지의 컨텍스트를 만든다."""

    return StreamContext(req)


@broken_derived
async def _(ctx: StreamContext, symbols: set[str], recv: Receiver):
    """첫 상위 데이터에서 던진다(계산 버그를 흉내 낸다)."""

    ctx.log.starts.append(frozenset(symbols))
    try:
        await recv()
        raise InjectedFailure("파생 계산이 실패했다.")
        yield  # async generator로 만든다
    finally:
        ctx.log.stopped += 1


@broken_derived.detached
async def _(ctx: StreamContext):
    ctx.log.detached += 1


class Explode(Runnable):
    """받는 족족 던지는 파이프라인 단계."""

    async def invoke(self, input: CounterData) -> SwingData | None:
        raise InjectedFailure("파이프라인이 실패했다.")


class FragileReq(SessionRequest):
    """`SwingReq`처럼 `BTC`를 `BTC/USD`로 구독하되, 지정한 심볼에서 실패하는 세션 요청.

    `failing` 심볼은 파이프라인이 던지고, `bind_fails` 심볼은 bind 콜백이 던진다.
    """

    tag: str
    failing: str = ""
    bind_fails: str = ""


@initialize
def fragile(req: FragileReq) -> StreamContext:
    """실패를 주입하는 세션 스테이지의 컨텍스트를 만든다."""

    return StreamContext(req)


@fragile
async def _(ctx: StreamContext, symbol: str):
    """심볼 하나의 파이프라인을 낸다. 설정한 심볼이면 던지거나 던지는 단계를 붙인다."""

    req = cast_model(ctx.req, FragileReq)
    if symbol == req.bind_fails:
        raise InjectedFailure(f"bind 콜백이 실패했다. - {symbol}")
    step = Explode() if symbol == req.failing else Relay(symbol)
    yield CounterReq(tag=req.tag)(f"{symbol}{QUOTE_SUFFIX}") | step


@fragile.unbind
async def _(ctx: StreamContext, symbol: str):
    ctx.log.unbound.append(symbol)


@fragile.detached
async def _(ctx: StreamContext):
    ctx.log.detached += 1


class FlakySplitReq(SessionRequest):
    """심볼마다 전용 `FlakyReq`(`flaky_upstream()`)에 붙는 세션 요청."""

    tag: str


def flaky_upstream(tag: str, symbol: str) -> FlakyReq:
    """`FlakySplitReq`의 심볼 `symbol`이 붙는 상위 요청. `trip(f"{tag}:{symbol}")`로 끊는다."""

    return FlakyReq(tag=f"{tag}:{symbol}")


@initialize
def flaky_split(req: FlakySplitReq) -> StreamContext:
    """심볼별로 끊기는 상위를 쓰는 세션 스테이지의 컨텍스트를 만든다."""

    return StreamContext(req)


@flaky_split
async def _(ctx: StreamContext, symbol: str):
    tag = cast_model(ctx.req, FlakySplitReq).tag
    yield flaky_upstream(tag, symbol)(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


@flaky_split.unbind
async def _(ctx: StreamContext, symbol: str):
    ctx.log.unbound.append(symbol)


class StubbornReq(SessionRequest):
    """정리 콜백(`unbind`·`detach`)이 기록을 남긴 뒤 던지는 세션 요청."""

    tag: str


@initialize
def stubborn(req: StubbornReq) -> StreamContext:
    """정리가 실패하는 세션 스테이지의 컨텍스트를 만든다."""

    return StreamContext(req)


@stubborn
async def _(ctx: StreamContext, symbol: str):
    tag = cast_model(ctx.req, StubbornReq).tag
    yield CounterReq(tag=tag)(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


@stubborn.unbind
async def _(ctx: StreamContext, symbol: str):
    ctx.log.unbound.append(symbol)
    raise InjectedFailure(f"unbind 콜백이 실패했다. - {symbol}")


@stubborn.detached
async def _(ctx: StreamContext):
    ctx.log.detached += 1
    raise InjectedFailure("detach 콜백이 실패했다.")


# ===== binder가 없는 요청 =====


class UnboundReq(SourceRequest):
    """일부러 binder를 등록하지 않은 요청. `DomainError` 검증에 쓴다."""

    tag: str
