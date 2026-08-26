"""도메인 테스트가 공유하는 요청·데이터 모델과 binder 정의.

`BindPack._binder_dict`는 프로세스 전역이라 **요청 타입 하나당 등록은 한 번뿐**이다.
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
    DependentModel,
    GenerateModel,
    Receiver,
    RequestModel,
    Runnable,
    cast_model,
    initialize,
)
from trading_core.model import BaseReqModel

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

    @property
    def last_start(self) -> frozenset[str]:
        """가장 최근 (재)시작이 받은 심볼 합집합."""

        return self.starts[-1]


_logs: defaultdict[str, StreamLog] = defaultdict(StreamLog)


def log_of(req: BaseReqModel) -> StreamLog:
    """요청의 content_id에 대응하는 기록을 돌려준다."""

    return _logs[req.get_tr_content_id()]


class StreamContext:
    """init 콜백이 만들어 스테이지 수명 동안 공유되는 컨텍스트."""

    def __init__(self, req: BaseReqModel) -> None:
        self.req = req
        self.log = log_of(req)
        self.log.inits += 1


# ===== 원천 제너레이터 =====


class CounterReq(GenerateModel):
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


class DerivedReq(DependentModel):
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


class MappedReq(DependentModel):
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


# ===== instanter(RequestModel) 스트림 =====
#
# `RequestModel`은 심볼마다 `Sequence`를 만들어 상위 원천에 붙이는 요청이다. 상위에
# 등록되는 심볼은 시퀀스가 요구한 표기(`BTC/USD`)이고 소비자가 받는 심볼은 하위
# 표기(`BTC`)다. 이 둘을 **일부러 다르게** 두어야 상·하위를 뒤바꾼 회귀가 드러난다.


class SwingReq(RequestModel):
    """하위 `BTC`를 상위 `BTC/USD`로 바꿔 요구하는 요청형 모델."""

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
    """요청형 스테이지의 공유 컨텍스트를 만든다."""

    return StreamContext(req)


@swing
async def _(ctx: StreamContext, symbol: str):
    """심볼 하나를 상위 표기로 바꿔 구독하는 시퀀스를 낸다."""

    tag = cast_model(ctx.req, SwingReq).tag
    yield CounterReq(tag=tag)(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


@swing.detached
async def _(ctx: StreamContext):
    """마지막 구독이 사라질 때 호출된다."""

    ctx.log.detached += 1


# ===== require까지 쓰는 instanter 스트림 =====

BEACON_SYMBOL = "BEACON/USD"
"""`BeaconReq`가 구독 심볼과 무관하게 항상 상위에 올리는 심볼."""


class BeaconReq(RequestModel):
    """구독 심볼과 별개로 상위 심볼 하나를 늘 요구하는 요청형 모델."""

    tag: str


@initialize
def beacon(req: BeaconReq) -> StreamContext:
    """require를 쓰는 요청형 스테이지의 공유 컨텍스트를 만든다."""

    return StreamContext(req)


@beacon
async def _(ctx: StreamContext, symbol: str):
    """`SwingReq`와 같은 방식으로 심볼별 시퀀스를 낸다."""

    tag = cast_model(ctx.req, BeaconReq).tag
    yield CounterReq(tag=tag)(f"{symbol}{QUOTE_SUFFIX}") | Relay(symbol)


@beacon.require
async def _(ctx: StreamContext):
    """구독 심볼이 무엇이든 항상 붙는 시퀀스."""

    tag = cast_model(ctx.req, BeaconReq).tag
    yield CounterReq(tag=tag)(BEACON_SYMBOL) | Relay(BEACON_SYMBOL)


# ===== binder가 없는 요청 =====


class UnboundReq(GenerateModel):
    """일부러 binder를 등록하지 않은 요청. `DomainError` 검증에 쓴다."""

    tag: str
