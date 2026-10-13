# trading-core

[English](README.md) | **한국어**

코인·주식 실시간 스트림을 위한 **타입 안전 비동기 스트리밍 오케스트레이션 코어**입니다.

`trading-core`는 거래소나 증권사에 종속된 WebSocket 클라이언트가 **아닙니다.** 실시간
시세·체결·호가 스트림을 다룰 때마다 반복되는 일 — 요청 모델링, 구독 공유, 심볼별 라우팅,
의존 스트림 연결, 태스크와 자원의 수명 주기, 실패 알림 — 을 작은 범용 런타임으로 제공합니다.
거래소별 인증·구독 메시지·응답 파싱은 **binder**(요청 타입에 붙이는 콜백)로 구현하고, 나머지
흐름은 코어가 같은 구조로 운용합니다.

## 무엇을 해결하나

여러 전략과 지표가 같은 종목을 동시에 구독합니다. 소비자마다 연결을 새로 만들면 연결 수와
트래픽이 늘고, 구독 추가·해제와 연결 종료도 각자 처리해야 합니다.

```text
소비자 A (BTC, ETH) ─┐
                     ├─→ 공유 소스 스테이지 (BTC, ETH, XRP) ─→ 심볼 기준 fan-out ─→ 각 소비자
소비자 B (ETH, XRP) ─┘
```

- **내용이 같은 요청은 공유** — 필드 값이 같은 요청은 컨텍스트와 generator 하나를 나눠 씁니다.
- **심볼 합집합** — binder는 소비자들이 원하는 심볼의 합집합만 받고, 합집합이 바뀔 때만
  재시작합니다.
- **심볼별 fan-out** — 데이터는 그 심볼을 구독한 소비자에게만 갑니다.
- **의존 스트림** — 한 요청의 출력을 다른 요청의 입력으로 잇고, 상위 스트림도 공유합니다.
- **심볼별 상태** — 차트 분석처럼 심볼마다 상태를 갖는 계산은 슬롯을 따로 둡니다.
- **명시적 수명 주기** — 구독 구성이 바뀔 때와 마지막 소비자가 떠날 때 각각 정리 지점이 있습니다.
- **실패 알림** — 실패를 재시도로 숨기지 않고, 영향받은 소비자에게 각자 잃은 심볼만 알립니다.
- **느린 소비자 격리** — 소비자 하나가 느리거나 막혀도 공유 스트림과 다른 소비자를 붙잡지 않고,
  너무 밀리면 그 소비자만 끊습니다.
- **타입이 있는 경계** — 요청과 데이터는 Pydantic 모델입니다. 검증·직렬화·복원을 그대로 씁니다.

## 설치

- Python 3.14 이상
- 런타임 의존성: [Pydantic 2](https://docs.pydantic.dev/) 하나뿐
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/bynaki/trading-core.git
cd trading-core
uv sync
```

다른 uv 프로젝트에서 의존하려면 로컬 경로나 Git 저장소를 씁니다.

```bash
uv add /path/to/trading-core
uv add "git+https://github.com/bynaki/trading-core.git"
```

## 빠른 시작

쓰는 일은 두 쪽으로 나뉩니다. **binder 쪽**은 요청 모델을 정의하고 그 요청이 오면 데이터를
어떻게 만들지 등록합니다(실제라면 여기서 거래소에 접속해 파싱합니다). **소비자 쪽**은 `Domain`에
요청과 심볼을 주고 데이터를 받습니다.

```python
import asyncio

from trading_core import DataModel, Domain, SourceRequest, cast_model, initialize


# ----- binder 쪽 -----
class TickReq(SourceRequest):
    exchange: str  # 필드 값이 요청의 '내용'이고, 내용이 같으면 공유된다


class TickData(DataModel):  # `symbol` 필드는 DataModel에 이미 있다(라우팅 키)
    price: float


@initialize  # 첫 인자의 어노테이션(TickReq)으로 어느 요청의 binder인지 정한다
def tick(req: TickReq) -> TickReq:
    """init 콜백: 스테이지가 설 때 한 번 불려 컨텍스트를 만든다(연결 객체 등)."""
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """generate 콜백: 구독 심볼의 합집합을 받아 데이터를 끝없이 내보낸다."""
    price = 100.0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=price)
        price += 1
        await asyncio.sleep(0.2)


# ----- 소비자 쪽 -----
async def main() -> None:
    domain = Domain()
    await domain.start()
    try:
        async with domain.stream(TickReq(exchange="mock"), {"BTC", "ETH"}) as stream:
            async for data in stream:
                tick_data = cast_model(data, TickData)  # DataModel → TickData
                print(tick_data.symbol, tick_data.price)
                if tick_data.price >= 102:
                    break  # 블록을 벗어나면 구독이 끊기고 generator가 닫힌다
    finally:
        await domain.stop()


asyncio.run(main())
```

`@initialize`가 실행되어야 요청을 쓸 수 있으므로, binder를 정의한 모듈은 `Domain`을 쓰기 전에
import되어 있어야 합니다.

## 핵심 개념

### 요청 세 종류

| 요청 | 하는 일 | 공유 | binder가 받는 것 |
| --- | --- | --- | --- |
| `SourceRequest` (소스 요청) | 외부에서 데이터를 받아 온다 | 내용이 같으면 공유 | `(ctx, symbols)` |
| `DerivedRequest` (파생 요청) | 다른 요청의 데이터를 받아 가공한다 | 내용이 같으면 공유 | `(ctx, symbols, recv)` |
| `SessionRequest` (세션 요청) | 심볼마다 상태를 갖고 파이프라인을 돌린다 | 공유하지 않음 | 심볼마다 `(ctx, symbol)` |

데이터는 모두 `DataModel`이고, `symbol` 필드로 소비자에게 라우팅됩니다.

### 구독: `stream()`과 `subscribe()`

`stream(req, symbols)`는 심볼을 처음에 정하고 끝까지 가는 간편 API입니다. 구독을 열어 둔 채
심볼을 바꾸려면 `subscribe()`를 씁니다. 데이터는 `Sender`(데이터 하나를 받는 async 함수)로 옵니다.

```python
async def on_tick(data: DataModel) -> None: ...


async def on_error(failed: StageFailed) -> None:
    # failed.symbols: 이 소비자가 잃은 심볼, failed.cause: 원인 요약
    ...


async with domain.subscribe(TickReq(exchange="mock"), on_tick, on_error) as sub:
    await sub.update({"BTC"})
    await sub.update({"ETH", "XRP"})  # 추가가 아니라 교체다 — BTC는 빠진다
    await sub.update(set())  # 빈 집합은 구독 해제
```

`domain.get_shared_symbols(req.tr_content_id)`로 공유 스테이지가 지금 돌리는 심볼 합집합을 볼 수
있습니다.

### 정리 지점 두 개

```python
@tick
async def _(ctx: Connection, symbols: set[str]):
    try:
        ...  # yield
    finally:
        ...  # 구독 심볼이 바뀌어 generator가 재시작될 때마다


@tick.detached
async def _(ctx: Connection):
    # 마지막 소비자가 떠나거나 스테이지가 실패해 내려갈 때 한 번 (연결 닫기 등)
    ...
```

컨텍스트는 재시작을 넘어 남습니다. 정리 콜백이 던져도 나머지 정리는 끝까지 합니다.

### 파생 요청: 다른 스트림 위에 쌓기

`require`로 상위 요청을 정하면 `Domain`이 상위 스테이지를 세우고 잇습니다. 소비자는 상위 요청을
몰라도 됩니다. 상위가 심볼을 다르게 부르면 심볼까지 바꿔 돌려줄 수 있습니다.

```python
class PriceReq(DerivedRequest):
    currency: str


@PriceReq.require
def _(req: PriceReq, symbols: set[str]):  # 심볼 인자를 빼면 심볼을 그대로 넘긴다
    return TickReq(exchange="mock"), {f"{s}/USD" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    while True:
        tick_data = cast_model(await recv(), TickData)  # 상위 데이터를 한 건씩 받는다
        yield PriceData(symbol=tick_data.symbol.removesuffix("/USD"), price=tick_data.price)
```

내용이 다른 파생 요청 여럿도 상위 요청이 같으면 상위 스테이지 하나를 나눠 쓰고, 상위는 하위들이
등록한 심볼의 합집합을 받습니다. 파생 위에 파생을 쌓을 수도 있습니다. 순환 의존은 지원하지 않고,
`require`가 심볼에 따라 다른 상위 요청을 고를 수는 없습니다.

### 세션 요청: 심볼마다 상태를 갖는 파이프라인

세션 요청은 심볼마다 **슬롯**을 하나씩 만들고, 각 슬롯은 bind 콜백이 내놓은 `Pipeline`으로 상위
소스 스테이지에 붙습니다. 단계(`Runnable`)는 슬롯마다 따로 만들어지므로 심볼별 상태를 안전하게
들 수 있습니다.

```python
class Change(Runnable[TickData, ChangeData]):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.last: float | None = None  # 이 심볼만의 상태

    async def invoke(self, input: TickData) -> ChangeData | None:
        last, self.last = self.last, input.price
        if last is None:
            return None  # None이면 그 데이터는 여기서 멈춘다
        return ChangeData(symbol=self.symbol, change=input.price - last)


@initialize
def change(req: ChangeReq) -> ChangeReq:
    return req


@change  # bind: 새 심볼이 구독될 때마다 그 심볼로 한 번
async def _(ctx: ChangeReq, symbol: str):
    yield TickReq(exchange="mock")(f"{symbol}/USD") | Change(symbol)


@change.unbind  # 그 심볼의 슬롯이 닫힐 때. bind 하나에 정확히 한 번
async def _(ctx: ChangeReq, symbol: str): ...
```

`@change.always`로 구독 심볼과 무관하게 늘 붙는 파이프라인을 둘 수 있고, bind가 파이프라인을 여럿
yield하면 한 슬롯이 상위 여럿에 붙습니다. bind가 받는 `symbol`은 소비자가 쓴 **하위 표기**(`BTC`),
파이프라인 머리에 넣는 것은 상위가 아는 **상위 표기**(`BTC/USD`)입니다.

### 실패 처리

코어는 **재시도하지 않습니다.** init 콜백·generator·bind 콜백·파이프라인 단계가 던지면 그
스테이지나 슬롯을 내리고, 영향받은 소비자에게 **자기 심볼만** 담은 `StageFailed`를 `on_error`로
알립니다. 그 스테이지를 상위로 둔 파생·세션까지 연쇄되며, `__cause__`가 상위의 `StageFailed`를
가리킵니다.

- 실패한 심볼은 구독에서 빠집니다. 다시 받으려면 소비자가 `update()`로 다시 넣고, 그러면 새
  스테이지가 init부터 섭니다.
- 소비자(`Sender`) 하나가 던지면 그 소비자만 떼어 내고 공유 generator는 계속 돕니다.
- 심볼 하나만 줄 수 없을 때(상장 폐지 등) binder는 `SymbolRejected`를 던집니다. 스테이지는 남은
  심볼로 계속 돌고 그 심볼만 실패로 알립니다.
- `update()`·`subscribe()`는 실패를 던지지 않습니다. `on_error`가 없으면 ERROR 로그만 남습니다.
  `stream()`은 실패하면 `StageFailed`를 던지고 끝납니다.
- binder 누락 같은 등록 실수는 `BindError`·`DomainError`·`ModelError`로 호출자에게 바로 갑니다.

느린 소비자도 같은 방식으로 다룹니다. 코어는 소비자마다 크기 제한이 있는 큐에 넣기만 하므로 소비자
하나가 느리거나 막혀도 공유 generator와 다른 소비자는 제 속도로 돕니다. 큐가
`Domain(sender_buffer=1000)`건까지 차면 데이터를 버리지 않고 끊어 `StageFailed`(원인
`SenderOverflow`)로 알립니다. 코어는 데이터를 버려도 되는지 모르기 때문입니다.

| 밀린 곳 | 끊기는 단위 |
| --- | --- |
| 소스·파생 요청의 소비자 | 그 소비자의 구독 전체 |
| 파생 generator(상위를 따라가지 못함) | 그 파생 스테이지 전체 (소비자 모두에게 알림) |
| 세션 슬롯(파이프라인이나 소비자가 느림) | 그 심볼 하나 |
| `stream()`을 읽는 쪽 | 받은 것을 다 내준 뒤 `StageFailed`를 던지고 끝남 |

막힌 연결을 얼마나 기다릴지는 `Sender`가 정합니다. Sender 안에서 `asyncio.timeout()`을 걸어 던지면
큐가 차기를 기다리지 않고 그 소비자만 곧바로 떨어집니다. 최신 값만 필요해 버려도 되는 소비자는 자기
큐로 받아 직접 버리면 끊기지 않습니다(ex25).

재연결처럼 무해한 끊김을 버틸지는 binder가 generator 안에서 정합니다. 코어까지 다시 시도하면
요청이 여러 단계를 거칠 때 재시도가 단계마다 곱해지기 때문입니다.

### 모델 식별자와 직렬화

| 식별자 | 무엇을 가리키나 | 쓰임 |
| --- | --- | --- |
| content_id (`req.tr_content_id`) | 모델 타입 + 내용 | 스테이지 공유의 기준 |
| model_id (`get_model_id`) | 클래스와 필드 구조 | binder 레지스트리 키, `cast_model()`의 일치 기준 |
| uid (`get_model_uid`) | 개별 인스턴스 | 어느 프로세스가 만든 어느 모델인지 추적 |

모델은 가변이고 고치면 content_id가 다시 계산됩니다. 그래서 hashable이 아니니 `set`·dict 키에는
content_id를 씁니다. `Domain`은 구독할 때 요청의 사본을 찍어 두므로 구독한 뒤 원본을 고쳐도
구독에는 영향이 없습니다.

`model_dump()`에는 `tr_annotation`이 붙고, `load_model()`이 그 정보로 원래 클래스를 찾아 복원합니다.
`parse_dump()`는 덤프만 검증하고, 입력이 맞지 않으면 `ModelValidationError`가 납니다.

### 로그

`trading_core.logger`는 콘솔·파일·로그서버 싱크를 켜고 끄는 JSON 로거입니다. 설정은
`setting.toml`의 `[log]` 카테고리에 두고(모든 키는 [setting.example.toml](setting.example.toml)에
설명), 레코드마다 `service`·`host`·`pid`로 발신처를 남깁니다. 코어 내부와 앱의 로거를 같은 싱크로
모읍니다.

```python
from trading_core.logger import configure, get_logger

# 생략하면 첫 로그 때 TRADING_CORE_SETTINGS → ./setting.toml 순으로 찾는다
configure("setting.toml")
log = get_logger("my_app.strategy")
log.info("주문 신호", symbol="BTC", price=101.0)
```

로그서버로 실제 전송하는 부분은 아직 없습니다(`[log.server] enabled = true`이면 구성 단계에서
오류).

## 예제

`examples/`에 기능이나 사건 하나에 파일 하나씩, **실행되는** 예제 34개가 있습니다. 각 파일 맨 위에
무엇을 배우는지와 기대 출력이 있고, 핵심 지점마다 `assert`가 있어 끝까지 돌면 예제가 보이는 동작이
지금 코드에서도 그대로라는 뜻입니다.

| 묶음 | 예제 | 내용 |
| --- | --- | --- |
| 1부 | ex01–06 | 소스 요청의 기본: `stream`·`subscribe`, 정리 지점, 공유, 합집합, 재시작 |
| 2부 | ex07–10 | 파생 요청: `require`, 심볼 변환, 상위 고르기, 파생 위의 파생 |
| 3부 | ex11–16 | 세션 요청: 슬롯·`Pipeline`, unbind, 공유하지 않음, 여러 단계·여러 상위, `always` |
| 4부 | ex17–24 | 실패: `StageFailed` 연쇄, 소비자 실패, 정리 실패, init 실패, `SymbolRejected` |
| 5부 | ex25–29 | 느린 소비자: 남을 붙잡지 않음, 타임아웃, 소스·파생·세션·`stream()`이 밀려 끊길 때 |
| 6부 | ex30–34 | 등록 실수, 식별자, 직렬화, 로그, 데이터 여러 종류 |

```bash
uv run examples/ex01_stream.py    # 파일 하나를 직접 실행
uv run examples/main.py ex01      # 번호로 실행
uv run examples/main.py serial    # 전체를 Domain 하나에서 차례로
uv run examples/main.py parallel  # 전체를 Domain 하나에서 동시에
uv run examples/main.py --help    # 예제 목록
```

전체 목차는 [examples/README.md](examples/README.md)에 있습니다. 처음이라면 ex01부터 차례로 보세요.
4부와 ex27·ex28의 ERROR 로그와 트레이스백은 예제가 일부러 낸 실패의 기록입니다.

## 범위와 한계

버전 `0.1.0`입니다.

코어가 담당하는 것:

- 요청·데이터 모델, 내용 기반 식별자, 직렬화·복원
- binder 등록과 요청 타입 기반 조회
- 내용이 같은 요청의 in-memory 스테이지 공유, 심볼 합집합 관리와 소비자별 라우팅
- 의존 스트림 연결과 심볼별 상태를 갖는 세션 스트림
- 비동기 태스크 취소와 binder·컨텍스트 정리 지점
- 심볼 단위 실패 알림
- 소비자별 크기 제한 큐로 느린 소비자 격리 (밀리면 버리지 않고 끊음)
- 발신처를 남기는 JSON 로그

binder나 앱이 직접 다뤄야 하는 것:

- 특정 거래소·증권사의 WebSocket/REST 클라이언트
- 인증, heartbeat, 자동 재연결, 재구독, rate limit (코어는 실패를 알리기만 하고 다시 시도하지 않음)
- 거래소 심볼과 내부 표준 심볼의 변환 규칙
- sequence 누락, snapshot/delta 정합성, 중복·순서 뒤바뀜 처리
- 주문 실행, 포트폴리오, 리스크, 저장소, 전략·지표 구현
- 프로세스·서버 간 스트림 공유
- 막힌 연결을 얼마나 기다릴지(`Sender` 안의 타임아웃)와 오래된 데이터를 버릴지 (코어는 버리지
  않고 끊기만 함 — ex25에 자기 큐로 받아 버리는 방법이 있음)

## 개발

```bash
uv run ruff check .
uv run ruff format --check .   # 적용은 uv run ruff format .
uv run pyright
uv run pytest
```

코드를 고치면 네 검사를 모두 통과시킵니다. 테스트는 예제를 돌리지 않으므로 `src/`를 고쳤으면
`uv run examples/main.py serial`도 돌려 보세요. 구조와 설계 불변식은 아래
[아키텍처](#아키텍처) 절에 정리되어 있습니다.

## 아키텍처

내부 구조와 설계 불변식입니다. 코어를 고치거나 동작을 깊이 이해하려는 사람을 위한 절이고,
사용법은 위의 "핵심 개념"과 예제를 보세요.

### 레이어

| 파일 | 책임 |
| --- | --- |
| `model.py` | `TrBaseModel` 계열 요청/데이터 모델, 3종 식별자, 직렬화·복원, `Pipeline`/`Runnable` |
| `binder.py` | `initialize()` 데코레이터와 `BindPack` 전역 레지스트리 (요청 타입 → 콜백) |
| `domain.py` | `Domain`, `Subscription`/`SharedStage`, 수명 주기 |
| `routing.py` | 프로세스 안 전달: `Channel`, `SymbolRouter`/`UpstreamRouters`, `PipelineSender` |
| `tasks.py` | 이름 기반 취소를 지원하는 비동기 `TaskManager` |
| `ids.py` | digest/id 생성, 정의 모듈 찾기 |
| `logger.py` | 프로젝트 전반 로그 모듈. `setting.toml` `[log]`로 콘솔·파일·로그서버 싱크를 켜는 JSON 로거 |
| `exceptions.py` | 프레임워크 예외 |

### 모델 계층

```
TrBaseModel
├── BaseRequest            (_tr_model_type = "unregistered")
│   ├── SourceRequest      → 바인드되면 "source"   (소스 요청)
│   ├── DerivedRequest     → 바인드되면 "derived"  (파생. require로 상위 요청 선언)
│   └── SessionRequest     → 바인드되면 "session"  (세션. 상태를 가져 공유하지 않음)
└── DataModel              (_tr_model_type = "data", symbol: str 라우팅 키)
```

`_tr_model_type`은 `BindPack.set_*_cb()`가 실행될 때 기록됩니다. **모듈이 import되어 데코레이터가
실행되어야** 요청을 쓸 수 있습니다. `Domain`은 이 값으로 스테이지 종류를 고릅니다. 이 값은
직렬화되어 `tr_annotation.model_type`에 실립니다.

식별자 3종은 역할이 다릅니다.

- **uid** (`_tr_uid`, `get_model_uid`): `클래스@모듈:인스턴스ID:순번`. 개별 모델 추적용입니다. 인스턴스
  ID는 모델을 만든 프로세스의 것(`set_instance_id`/`get_instance_id`, `get_model_created_by`)입니다.
  기본값은 로그 발신처 `instance_id`(`service@host:pid`, `logger.get_identity()`)에 6자리 무작위 꼬리를
  붙인 것이라 `@`·`:`가 들어 있습니다. uid를 구분자로 쪼개지 마세요. 처음 만든 모델이 값을 정하므로
  `service_name`을 바꿔 `configure()`하려면 모델을 만들기 전에 합니다.
- **model_id** (`get_model_id`): `클래스@모듈:필드이름구조digest`. binder 레지스트리 키이자
  `cast_model()`의 일치 기준(상속이 아니라 정확한 일치)입니다.
- **content_id** (`tr_content_id`): 모델 타입 + JSON 직렬화 내용의 digest. **공유의 기준**입니다.
  캐시하며, 필드를 골라 계산하려면 `compute_tr_content_id(include, exclude)`를 씁니다.

모델은 **가변**이고 `__setattr__`이 content_id 캐시를 무효화합니다. 그래서 hashable이 아닙니다.
`set`·dict 키로 쓰지 말고 content_id를 키로 쓰세요. 직렬화 시 `tr_annotation`이 붙고,
`load_model()`은 그 `module_name`/`model_name`으로 클래스를 되찾아 복원합니다(`parse_dump()`는
덤프만 검증합니다). 가변이라 `Domain`은 구독할 때 요청을 **사본으로 찍어 둡니다**
(`_create_subscription()`). 구독한 뒤 호출자가 요청을 고쳐도 구독은 처음 내용에 묶여 있고,
`Subscription.request`도 사본을 줍니다. 안 그러면 바뀐 content_id로 스테이지를 찾아 처음 스테이지가
닫히지 않습니다.

### 등록 (binder.py)

```python
@initialize  # init 콜백의 첫 파라미터 어노테이션으로 요청 타입을 추론
def naming(req: NamingAllReq) -> NamingAllContext:
    return NamingAllContext(req)  # content_id 수명 동안 공유되는 컨텍스트


@naming  # SourceBinder.__call__ → generate 콜백
async def _(ctx: NamingAllContext, symbols: set[str]):
    yield NamingAllData(...)


@naming.detached  # 마지막 구독이 사라질 때 컨텍스트 정리
async def _(ctx: NamingAllContext): ...
```

- `initialize()`는 `get_type_hints(cb)`의 **첫 값**을 요청 타입으로 씁니다(어노테이션 필수). 요청
  타입에 따라 `SourceBinder` / `DerivedBinder` / `SessionBinder`를 반환합니다.
- `DerivedRequest`는 **인자 없는** 데코레이터 `require`로 상위 요청을 선언합니다. 두 형태를 받고
  위치 인자 개수로 구분해 `RequireCbWithSym`으로 정규화합니다(`resolve_upstream(symbols)`로
  꺼냅니다). require 없이 파생 스테이지를 만들면 `ModelError`입니다.

  ```python
  @NamingReq.require  # RequireCb — 요청만 받는다
  def _(req: NamingReq) -> origin.NamingAllReq:
      return origin.NamingAllReq()


  @PriceRequest.require  # RequireCbWithSym — 심볼까지 변환한다
  def _(req: PriceRequest, symbols: set[str]):
      return origin.TickReq(), {f"{s}/USD" for s in symbols}
  ```

- 파생 binder는 `(ctx, symbols, recv: Receiver)`를 받습니다. `recv()`로 상위 데이터를 받아
  `cast_model()`로 좁힙니다.
- `SessionRequest`는 `@x`(bind) · `@x.unbind` · `@x.always` · `@x.detached`를 붙입니다. bind와
  always는 하나씩만 등록되고 두 번째는 `BindError`입니다. 파생의 `require`(상위 요청 선언)와 세션의
  `always`(늘 붙는 파이프라인)는 다른 것입니다.
- `BindPack._registry`는 **프로세스 전역**입니다(`BindPack.lookup(model_id)`). 같은 `model_id`를 두 번
  등록하면 `BindError`입니다.

### 실행 (domain.py)

핵심 불변식:

1. **content_id 단위 공유** — 소스·파생 스테이지는 `_shared_stages[content_id]`에 `SharedStage`가
   하나만 있습니다. 같은 요청의 소비자들은 컨텍스트와 generator를 공유합니다. 세션 요청은 공유하지
   않습니다.
2. **심볼 합집합** — `SymbolRouter`가 (Sender, symbols)를 모아 binder에는 **합집합**만 넘기고,
   출력은 `data.symbol`을 구독한 Sender에게만 fan-out합니다.
3. **합집합이 바뀔 때만 재시작** — `current_symbols == active_symbols`면 `update()`는 즉시
   반환합니다. 달라지면 태스크를 이름으로 취소하고(generator는 `pump()`가 `aclosing`으로 닫습니다)
   새 generator를 만듭니다(소스·파생 스테이지 한정).
4. **두 개의 정리 지점** — binder의 `finally`는 구독 업데이트 단위, `@x.detached`는 스테이지
   전체입니다. 합집합이 비면 스테이지를 dict에서 빼고 detach 콜백을 부릅니다.
5. **`update(symbols)`는 교체입니다**(`SymbolRouter.replace()`). 빈 집합을 넘기면 그 소비자의 구독이
   사라집니다.
6. **bind ↔ unbind 짝** — 세션에서 `bind_cb`로 연 심볼은 `update()`로 빠지든 `detach()`로 닫히든
   `unbind_cb`가 **정확히 한 번** 불립니다(`unbind_symbols()` 공유). 슬롯 닫기(`close_slots()`)는
   슬롯 태스크의 이름 해제까지 기다립니다.
7. **실패는 재시도하지 않고 심볼 단위로 알립니다** — init 콜백·소스·파생 generator·파이프라인·bind
   콜백·소비자 `Sender`가 던지면 그 스테이지나 슬롯을 내리고(init이면 세우지 않고), 영향받은
   소비자에게 **자기 심볼만** 담은 `StageFailed`를 `on_error`로 알립니다. `update()`·`subscribe()`는
   던지지 않습니다. 소스·파생 스테이지가 실패하면(init 실패 포함) 그 스테이지를 상위로 둔 파생·세션
   슬롯으로 연쇄합니다(`__cause__`가 상위의 `StageFailed`). `Sender` 하나가 던지면 그 Sender만 떼고
   공유 generator는 계속 돕니다. **느린 `Sender`도 남을 붙잡지 않습니다** — 공유 구독은 소비자마다
   `SenderOutbox`(크기 제한 큐 + 전달 태스크 `{sub.id}:out`)를 라우터에 등록하고, 세션은 슬롯 채널에
   상한을 둡니다. 둘 다 `Domain(sender_buffer)`건까지 차면 버리지 않고 그 소비자(세션은 그 슬롯)만
   `SenderOverflow`로 실패시킵니다. 데이터를 버려도 되는지 코어는 모르기 때문입니다. 막힌 연결을
   얼마나 기다릴지는 `Sender`가 스스로 정합니다(타임아웃이 지나면 던집니다). 실패한 outbox는 다음
   호출에서 그 예외를 던져 라우터의 `fail_sender()` 길을 타고, 전송이 던졌을 때는 다음 데이터를
   기다리지 않고 `on_failed`로도 뗍니다. 파생 스테이지가 상위 데이터를 받는 채널도 같은 상한입니다.
   파생 generator가 밀려 차면 상위를 붙잡지 않고 **그 파생 스테이지 전체**가 `SenderOverflow`로
   실패합니다. 상위 라우터로 던지지 않으므로 상위의 실패로 알려지지 않습니다. `stream()`은 한 건짜리
   채널을 써서 읽는 쪽이 밀리면 outbox가 차서 끝납니다. 실패한 심볼은 구독에서 빠지고, `update()`로
   다시 넣으면 새 스테이지가 init부터 섭니다. 버틸지(재연결 등)는 binder가 generator 안에서 정합니다.
   세션도 공유 스테이지처럼 init을 첫 `update()`에서 합니다. binder 누락 같은 등록
   오류(`DomainError`)는 호출자에게 그대로 갑니다. 소스·파생 generator가 `SymbolRejected(symbols)`를
   던지면 스테이지를 내리지 않고 그 심볼만 구독에서 빼 알리고, 남은 심볼로 다시 띄웁니다
   (`fail_symbols()`). 파생은 상위의 실패 심볼을 하위 심볼로 되돌려(`fail_upstream_symbols()`, 하위
   심볼마다 `resolve_upstream({s})`) 그것만 뺍니다. 구독되지 않은 심볼만 거부하면 같은 합집합으로
   끝없이 다시 띄우지 않도록 스테이지 전체의 실패로 봅니다.
8. **정리 실패는 정리를 막지 않습니다** — `detach_cb`·`unbind_cb`·binder `finally`가 던져도 나머지
   정리를 끝까지 하고(`_run_cleanups()`, 형제를 취소하지 않습니다) ERROR 로그만 남깁니다.
   `update()`·`detach()`의 호출자에게 올리지 않습니다.

소비 API: `Domain.stream(req, symbols)`는 async generator를 줍니다(`aclosing`으로 감싸 조기
`break`에도 정리합니다). `Domain.subscribe(req, sender)`는 호출자가 `Sender`를 주고
`sub.update(symbols)`로 심볼을 교체하는 저수준 API입니다(`Subscription`을 줍니다).
`subscribe(req, sender, on_error)`의 `on_error`가 `StageFailed`(`content_id`·`symbols`·`cause`)를
받습니다. 없으면 ERROR 로그만 남습니다. `stream()`은 테스트·예제용 간편 API라 실패하면
`StageFailed`를 던지고 끝납니다. `get_shared_symbols(content_id)`는 공유 중인 스테이지의 심볼
합집합을 돌려줍니다(공유 중이 아니면 빈 집합). `Subscription`·`SharedStage`는
`_STAGE_CREATION_KEY` 가드로 `Domain`을 통해서만 만들어집니다. 공개 API는 작게 두고 내부
객체(스테이지)를 돌려주지 않습니다.

의존 스트림: `_update_shared_stage()`가 상위 `SharedStage`를 만들거나 재사용하고, 상한이 있는
`Channel`로 하위 binder의 `recv`에 잇습니다. 상위 라우터에는 채널 대신 스테이지마다 한 번 만든
`receive`(기다리지 않고 넣고, 차면 이 스테이지를 실패시킵니다)를 등록합니다. 상위도 content_id·합집합
기준으로 공유됩니다. 순환 의존은 지원하지 않습니다. 파생 스테이지는 상위 하나만 바라보므로
**require 콜백이 심볼에 따라 다른 상위 요청을 반환할 수 없습니다.**

#### 세션 (SessionRequest)

소스·파생 스테이지가 "심볼 집합 하나 → generator 하나"라면, 세션은 **심볼마다 슬롯 하나**를 만들고
각 슬롯이 `Pipeline`으로 상위 소스 스테이지에 붙습니다(`Domain._create_session_subscription()`,
예: ex11, 테스트의 `SwingReq`). 차트 분석처럼 상태를 가지므로 content_id가 같아도 공유하지
않습니다(ex13).

```python
@swing  # bind — 심볼 하나의 Pipeline을 yield
async def _(ctx: SwingCtx, symbol: str):
    yield TickReq()(f"{symbol}/USD") | SwingRunnable(symbol)


@swing.unbind  # 그 심볼의 슬롯이 닫힐 때
async def _(ctx: SwingCtx, symbol: str): ...


@swing.always  # 구독 심볼과 무관하게 늘 붙는 Pipeline
async def _(ctx: SwingCtx):
    yield TickReq()("HEARTBEAT/USD") | ...
```

**상위 표기와 하위 표기를 구분합니다.** `req(symbol)`의 `symbol`은 상위 표기(소스 스테이지가 아는
`"BTC/USD"`, `Pipeline.upstream_symbol`), bind 콜백이 받는 `symbol`은 하위 표기(소비자가 구독한
`"BTC"`)입니다. 상·하위가 같은 요청으로만 시험하면 둘을 뒤바꾼 버그가 안 드러납니다.

- 상위 구독에 등록하는 심볼은 `route.router.symbols`(상위 표기)입니다. 하위 심볼이 아닙니다.
- `_ALWAYS_SLOT`(`"__always__"`)은 `always_cb` 슬롯의 키 센티널입니다. bind된 적이 없으므로
  `unbind_cb` 대상이 아니고, 실제 심볼 계산에 섞여서도 안 됩니다.
- `UpstreamRouters`는 content_id별로 `SymbolRouter` **객체** 하나를 유지합니다(`Sender` 동일성 검사
  때문). `clear()`는 라우터만 비우고, 다시 채운 뒤 `prune()`이 센더 없는 항목을 지우며 그 상위
  구독을 같은 `update()`에서 떼어 냅니다.
- 데이터 흐름: 소스 스테이지 → `SymbolRouter`(상위 표기) → `PipelineSender` → 슬롯 `Channel` →
  `_run_pipeline_slot()`이 `pipeline.invoke()`를 거쳐 소비자에게. `PipelineSender`는 슬롯 채널에
  기다리지 않고 넣고(`try_send()`), 가득 차면 데이터를 버리고 그 슬롯을 실패시킵니다(기다리면
  상위가 멈춥니다).
- 슬롯은 상위 구독 갱신보다 먼저 닫히므로, 닫힌 슬롯으로 온 데이터의 `ChannelClosed`는
  `PipelineSender`가 삼킵니다. 올려 보내면 공유된 상위 generator가 죽습니다.
- 상위가 실패하면 상위 표기로 온 `StageFailed`를 그 상위·심볼을 쓰던 슬롯 키(하위 표기)로 되돌려
  알립니다(`on_upstream_failed()`). `always` 슬롯이 실패하면 세션 구독 전체가 실패하고 컨텍스트도
  정리해, 다음 `update()`가 init부터 다시 합니다.

#### 실패 처리의 락 순서

스테이지 락은 **하위 → 상위** 순서로만 잡습니다(하위 `update()`가 상위 `update()`를 부릅니다).
그래서 실패 통지(`OnFail`)는 락을 잡지 않고 `Domain._spawn()`으로 태스크만 띄웁니다. 상위 락을 쥔
채 하위에 알리면 교착합니다. 실패 처리 태스크는 세대 번호(`run_seq`)로 그 사이 `update()`가 새
generator를 띄웠는지 가려내고, 빠진 스테이지(`retired`)로 온 `update()`는 지금 등록된 스테이지로
넘깁니다.

### TaskManager (tasks.py)

`Domain`의 generator 루프는 모두 `TaskManager.submit(coro, name)`으로 돕니다. 이름이 태스크의
정체성이고 **대기 중에도 점유**됩니다. `cancel_by_name()`은 실행 중이면 취소 후 `gather`, 대기
중이면 `_cancelled_pending`에 예약하고, 어느 쪽이든 **이름 해제까지 기다립니다**(안 그러면 같은 이름
재제출이 충돌합니다). `live_count`는 끝나지 않은(대기 + 실행) 태스크 수입니다. 제출·완료·취소 훅은
`logger.py`로 DEBUG 로그를, 예외 훅은 ERROR 로그를 남깁니다(태스크까지 새어 나온 예외는 `Domain`이
처리하지 못한 버그입니다).

## 라이선스

[MIT License](LICENSE)
