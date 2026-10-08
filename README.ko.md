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
async def on_tick(data: DataModel) -> None:
    ...

async def on_error(failed: StageFailed) -> None:
    ...  # failed.symbols: 이 소비자가 잃은 심볼, failed.cause: 원인 요약

async with domain.subscribe(TickReq(exchange="mock"), on_tick, on_error) as sub:
    await sub.update({"BTC"})
    await sub.update({"ETH", "XRP"})  # 추가가 아니라 교체다 — BTC는 빠진다
    await sub.update(set())           # 빈 집합은 구독 해제
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
    ...  # 마지막 소비자가 떠나거나 스테이지가 실패해 내려갈 때 한 번 (연결 닫기 등)
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

configure("setting.toml")  # 생략하면 첫 로그 때 TRADING_CORE_SETTINGS → ./setting.toml 순으로 찾는다
log = get_logger("my_app.strategy")
log.info("주문 신호", symbol="BTC", price=101.0)
```

로그서버로 실제 전송하는 부분은 아직 없습니다(`[log.server] enabled = true`이면 구성 단계에서
오류).

## 예제

`examples/`에 기능이나 사건 하나에 파일 하나씩, **실행되는** 예제 30개가 있습니다. 각 파일 맨 위에
무엇을 배우는지와 기대 출력이 있고, 핵심 지점마다 `assert`가 있어 끝까지 돌면 예제가 보이는 동작이
지금 코드에서도 그대로라는 뜻입니다.

| 묶음 | 예제 | 내용 |
| --- | --- | --- |
| 1부 | ex01–06 | 소스 요청의 기본: `stream`·`subscribe`, 정리 지점, 공유, 합집합, 재시작 |
| 2부 | ex07–10 | 파생 요청: `require`, 심볼 변환, 상위 고르기, 파생 위의 파생 |
| 3부 | ex11–16 | 세션 요청: 슬롯·`Pipeline`, unbind, 공유하지 않음, 여러 단계·여러 상위, `always` |
| 4부 | ex17–24 | 실패: `StageFailed` 연쇄, 소비자 실패, 정리 실패, init 실패, `SymbolRejected` |
| 5부 | ex25–30 | 느린 소비자, 등록 실수, 식별자, 직렬화, 로그, 데이터 여러 종류 |

```bash
uv run examples/ex01_stream.py    # 파일 하나를 직접 실행
uv run examples/main.py ex01      # 번호로 실행
uv run examples/main.py serial    # 전체를 Domain 하나에서 차례로
uv run examples/main.py parallel  # 전체를 Domain 하나에서 동시에
uv run examples/main.py --help    # 예제 목록
```

전체 목차는 [examples/README.md](examples/README.md)에 있습니다. 처음이라면 ex01부터 차례로 보세요.
4부의 ERROR 로그와 트레이스백은 예제가 일부러 낸 실패의 기록입니다.

## 범위와 한계

버전 `0.1.0`입니다.

코어가 담당하는 것:

- 요청·데이터 모델, 내용 기반 식별자, 직렬화·복원
- binder 등록과 요청 타입 기반 조회
- 내용이 같은 요청의 in-memory 스테이지 공유, 심볼 합집합 관리와 소비자별 라우팅
- 의존 스트림 연결과 심볼별 상태를 갖는 세션 스트림
- 비동기 태스크 취소와 binder·컨텍스트 정리 지점
- 심볼 단위 실패 알림
- 발신처를 남기는 JSON 로그

binder나 앱이 직접 다뤄야 하는 것:

- 특정 거래소·증권사의 WebSocket/REST 클라이언트
- 인증, heartbeat, 자동 재연결, 재구독, rate limit (코어는 실패를 알리기만 하고 다시 시도하지 않음)
- 거래소 심볼과 내부 표준 심볼의 변환 규칙
- sequence 누락, snapshot/delta 정합성, 중복·순서 뒤바뀜 처리
- 주문 실행, 포트폴리오, 리스크, 저장소, 전략·지표 구현
- 프로세스·서버 간 스트림 공유
- bounded queue와 backpressure (느린 소비자는 공유 스트림을 함께 늦춤 — ex25에 자기 큐로 떼어
  내는 방법이 있음)

## 개발

```bash
uv run ruff check .
uv run ruff format --check .   # 적용은 uv run ruff format .
uv run pyright
uv run pytest
```

코드를 고치면 네 검사를 모두 통과시킵니다. 테스트는 예제를 돌리지 않으므로 `src/`를 고쳤으면
`uv run examples/main.py serial`도 돌려 보세요. 구조와 설계 불변식은 [AGENTS.md](AGENTS.md)에
정리되어 있습니다.

## 라이선스

[MIT License](LICENSE)
