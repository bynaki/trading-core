# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

`trading-core`는 특정 거래소에 종속되지 않은 **타입 안전 비동기 스트리밍 오케스트레이션 코어**다.
WebSocket 클라이언트가 아니라, 실시간 스트림을 다룰 때 반복되는 요청 모델링 · 구독 공유 ·
심볼별 라우팅 · 의존 스트림 연결 · 태스크 수명 주기를 제공하는 런타임이다. 거래소별 인증 ·
구독 · 파싱은 사용자가 binder로 구현한다.

문서·주석·docstring·예외 메시지는 **한국어**로 작성한다. 기존 스타일을 따를 것.

## 명령

모든 명령은 `uv`로 실행한다(`uv run`이 항상 프로젝트 `.venv`를 쓰므로 `activate` 불필요).

```bash
uv run ruff check .          # 린트
uv run ruff format .         # 포맷 적용
uv run ruff format --check . # 포맷 검사
uv run pyright               # 타입 체크 (standard)
uv run pytest                # 테스트 (약 0.5초 — "테스트" 절 참고)
```

코드 변경 후 위 4개(check / format / pyright / pytest)가 모두 통과해야 한다. 넷 다 클린이다.
테스트가 프레임워크 불변식을 덮지만 예제까지 함께 도는 것은 아니므로, `src/`를 고쳤으면
`uv run examples/main.py serial`도 한 번 돌려 볼 것.

예제 실행:

```bash
uv run python examples/ex01/run_ex.py # 예제 파일을 직접 실행 (자체 Domain을 만든다)
uv run examples/main.py ex01          # 예제 이름으로 실행
uv run examples/main.py serial        # 모든 예제를 공유 Domain에서 순차 실행
uv run examples/main.py parallel      # 모든 예제를 공유 Domain에서 동시 실행
```

`examples/main.py`는 `examples/*/run_ex.py`를 글롭으로 찾아 예제 목록을 만든다. `run_ex(domain)`
코루틴을 가진 디렉터리를 추가하면 인자 목록(`--help`)과 `serial`/`parallel`에 자동으로 포함된다.

의존성: `uv add <pkg>` / `uv add --dev <pkg>`.

## 현재 저장소 상태 (중요)

2026-08-26 기준. 작업 브랜치는 **`feat/request_model`**이고 `main`보다 8커밋 앞서 있다. 이 브랜치가
하는 일은 `RequestModel`을 **instanter** 실행 경로로 확장하는 것이다(아래 "instanter" 절).
원격에는 `origin/main` · `origin/feat/request_model` · `origin/update/require`(옛 브랜치)가 있다.

- 등록 API 리팩터링(`definer.py` → `binder.py`)은 끝났고 `main`에 들어가 있다. `definer.py`
  (옛 `@generator` / `@task` / `@processor` 레지스트리)는 **삭제**되었고 코드에 옛 API 참조는 없다.
- `uv run ruff check` · `ruff format --check` · `pyright` · `pytest` **모두 클린이다**
  (pyright 0 errors, 87 tests passed). `examples/main.py serial`도 ex01~ex08 전부 완주한다.
- 예제는 `examples/ex01`~`examples/ex08` 여덟 개다. ex06은 파생 스테이지의 "합집합이 그대로면
  재시작하지 않는다"를, ex07·ex08은 instanter 경로를 다룬다. ex08은 요청형 스테이지가
  content_id로 공유되지 **않는다**는 것을 원천의 공유와 나란히 보인다.
- 문서 상태:
  - `README.md`는 **의도적으로 얇다.** 프로젝트 소개 · 설치 · 예제 실행법 · 범위와 한계만 두고
    **코드 예제와 API 이름을 넣지 않는다.** API가 아직 자리를 잡는 중이라 문서가 곧 낡기
    때문이고, 사용법은 실행되는 `examples/`가 담당한다(낡으면 바로 깨지므로 썩지 않는다).
    기능을 추가했다고 README에 API 설명을 다시 채워 넣지 말 것.
  - `examples/ex01`~`ex08`의 README와 코드 docstring은 모두 현행 API 기준이다. 예제를 고치면
    같은 디렉터리의 README도 함께 고칠 것 — 지금은 어긋난 곳이 없다.
- `TODO.md`에 남은 과제와 이미 해결한 불변식의 내력이 번호 순으로 적혀 있다. 특히 "require 콜백이
  심볼에 따라 다른 상위 요청을 반환할 수 없다"(2번)는 제약은 현재 구조상 유효하다.
- `playground.py`는 타입 실험용 스크래치 파일이다. 정식 예제가 아니다.

## 아키텍처

### 레이어

| 파일 | 책임 |
| --- | --- |
| `model.py` | `TrBaseModel` 계열 요청/데이터 모델, 3종 식별자, 직렬화·검증, `Sequence`/`Runnable` |
| `binder.py` | `initialize()` 데코레이터와 `BindPack` 전역 레지스트리 (요청 타입 → 콜백) |
| `domain.py` | `Domain`, `Stage`/`OriginStage`, `SendRouter`/`SendRouterSet`, `TransmitQueue`, 수명 주기 |
| `helper.py` | digest/id 생성, 이름 기반 취소를 지원하는 비동기 `TaskManager` |
| `exceptions.py` | 프레임워크 예외 |

### 모델 계층

`TrBaseModel`(pydantic `BaseModel`) 아래에 요청 계열과 데이터 계열이 나뉜다.

```
TrBaseModel
├── BaseReqModel          (_tr_model_type = "unregistered")
│   ├── GenerateModel     → 바인드되면 "generator"
│   ├── DependentModel    → 바인드되면 "dependent_generator"  (require로 상위 요청 선언)
│   └── RequestModel      → 바인드되면 "instanter"
└── DataModel             (_tr_model_type = "data", symbol: str 라우팅 키)
```

`_tr_model_type`은 `BindPack.set_*_cb()`가 실행될 때 클래스에 기록된다. 즉 **모듈이 import되어
데코레이터가 실행되어야** 해당 요청이 사용 가능해진다. `Domain`은 이 값으로 스테이지 종류를 고른다.

식별자 3종은 서로 역할이 다르다 — 헷갈리면 안 된다.

- **instance id** (`_tr_id`, `get_model_inst_id`): `클래스@모듈:출처:순번`. 개별 인스턴스 추적용.
- **model_id** (`get_model_id`): `클래스@모듈:필드이름구조digest`. `__init_subclass__`에서 계산되며
  binder 레지스트리 키이자 `cast_model()`의 일치 기준이다(상속 관계가 아니라 정확한 일치를 요구).
- **content_id** (`get_tr_content_id()`): 모델 타입 + JSON 직렬화 내용의 digest.
  **동일 원천 공유의 기준**이다. 필드 값이 같은 요청은 같은 origin stage를 쓴다.

모델은 **가변**이다. `__setattr__`이 content_id 캐시를 무효화한다. 그래서 요청 모델을 `set`에
넣거나 dict 키로 쓰면 안 된다(hashable이 아니다). 모아 둘 일이 있으면 content_id를 키로 쓴다.

모든 모델은 직렬화 시 `tr_annotation`(computed field)을 포함하고, `validate_model()`은 이 annotation의
`module_name`/`model_name`으로 클래스를 되찾아 복원한다.

### 등록 (binder.py)

```python
@initialize                      # init 콜백의 첫 파라미터 어노테이션으로 요청 타입을 추론
def naming(req: NamingAllReq) -> NamingAllContext:
    return NamingAllContext(req)  # content_id 수명 동안 공유되는 컨텍스트

@naming                          # GenerateModelBinder.__call__ → generate 콜백
async def _(ctx: NamingAllContext, symbols: set[str]):
    yield NamingAllData(...)

@naming.detached                 # 마지막 구독이 사라질 때 컨텍스트 정리
async def _(ctx: NamingAllContext): ...
```

- `initialize()`는 `get_type_hints(cb)`의 **첫 값**을 요청 타입으로 쓴다. 따라서 init 콜백의
  파라미터 어노테이션이 반드시 있어야 하고, 요청 타입에 따라 `GenerateModelBinder` /
  `DependentModelBinder` / `RequestModelBinder` 중 하나가 반환된다.
- `DependentModel`은 `require`로 상위 요청을 선언한다. **인자 없는** 데코레이터이고 두 형태를 받는다:

  ```python
  @NamingReq.require                    # RequireCb — 요청만 받는다
  def _(req: NamingReq) -> origin.NamingAllReq:
      return origin.NamingAllReq()

  @PriceRequest.require                 # RequireCbWithSym — 심볼까지 변환한다
  def _(req: PriceRequest, symbols: set[str]):
      return origin.TickReq(), {f"{s}/USD" for s in symbols}
  ```

  둘은 위치 인자 개수로 구분되어 `RequireCbWithSym`으로 정규화된다. 등록 순서는 강제되지 않지만
  (generate 바인드 뒤에 선언해도 등록은 통과한다) 예제는 모두 require를 먼저 쓴다. require 없이
  파생 스테이지를 만들면 그때 `ModelError`가 난다.
- dependent binder의 시그니처는 `(ctx, symbols, recv: Receiver)`로 인자가 하나 더 많다.
  `recv()`로 상위 원천 데이터를 받아 `cast_model()`로 좁혀 쓴다.
- `RequestModel`은 콜백 네 종을 붙인다 — `@x`(bind) · `@x.unbind` · `@x.require` · `@x.detached`.
  bind와 require는 각각 하나만 등록되고 두 번째는 `BindError`다. 아래 "instanter" 절 참고.
- `BindPack._binder_dict`는 **프로세스 전역 클래스 변수**다. 같은 `model_id`를 두 번 등록하면
  `BindError`가 난다. 테스트에서 예제 모듈을 여러 번 import해도 등록은 한 번뿐이라는 전제를 갖는다.

### 실행 (domain.py)

핵심 불변식:

1. **content_id 단위 공유** — `_origin_stage_dict[content_id]`에 origin stage가 하나만 존재한다.
   여러 소비자가 같은 요청을 보내면 컨텍스트와 generator를 공유한다.
2. **심볼 합집합** — `SendRouter`가 (Sender, symbols) 쌍을 모으고, binder에는 **합집합**만 넘긴다.
   출력은 `data.symbol`을 구독한 Sender에게만 fan-out된다.
3. **합집합이 바뀔 때만 재시작** — `update()`는 `current_symbols == active_symbols`면 즉시 반환한다.
   달라지면 이름으로 태스크를 취소하고 `gen.aclose()` 후 새 generator를 만든다. (원천·파생 한정.
   instanter는 generator가 없고 슬롯을 더하고 뺀다.)
4. **두 개의 정리 지점** — binder의 `finally`는 *구독 업데이트 단위* 정리, `@x.detached`는
   *스테이지 전체* 정리다. 합집합이 빈 집합이 되면 stage를 dict에서 제거하고 detach 콜백을 부른다.
5. **`update(symbols)`는 교체이지 추가가 아니다.** 빈 집합을 넘기면 그 소비자의 구독이 사라진다.
6. **bind ↔ unbind 짝** — instanter에서 `bind_cb`로 연 심볼은 `update()`로 빠지든 `detach()`로
   닫히든 `unbind_cb`가 **정확히 한 번** 불린다. 두 경로가 `unbind_symbols()` 헬퍼를 공유한다.

두 가지 소비 API:

- `Domain.request(req, symbols)` — 내부에서 `TransmitQueue`와 Stage를 만들어 async generator를 준다.
  `aclosing`으로 감싸져 있어 조기 `break`에도 구독이 정리된다.
- `Domain.stage(req, sender)` — 호출자가 `Sender`를 제공하고 `stage.update(symbols)`로 실행 중
  심볼 집합을 교체하는 저수준 API.

의존 스트림은 `_ensure_require_stage()`가 상위 요청의 origin stage를 만들거나 재사용하고,
`TransmitQueue`로 상위 출력을 하위 binder의 `recv`에 연결한다. 상위 원천도 동일하게 content_id와
합집합 기준으로 공유된다. 순환 의존은 지원하지 않는다.

`Stage`는 `_STAGE_CREATION_KEY` 가드로 `Domain`을 통해서만 생성된다.

#### instanter (RequestModel)

`GenerateModel`·`DependentModel`이 "심볼 집합 하나 → generator 하나"라면, `RequestModel`은
**심볼마다 슬롯 하나**를 만들고 각 슬롯이 `Sequence`로 상위 원천에 붙는 구조다
(`Domain._define_inst_stage()`). ex07과 `tests/support/streams.py`의 `SwingReq`가 예다.

```python
@swing                                   # bind — 심볼 하나의 Sequence를 yield
async def _(ctx: SwingCtx, symbol: str):
    yield TickReq()(f"{symbol}/USD") | SwingRunnable(symbol)

@swing.unbind                            # 그 심볼의 슬롯이 닫힐 때
async def _(ctx: SwingCtx, symbol: str): ...

@swing.require                           # 구독 심볼과 무관하게 늘 붙는 Sequence
async def _(ctx: SwingCtx):
    yield TickReq()("HEARTBEAT/USD") | ...
```

`Sequence`는 `req(symbol) | Runnable | ...`로 만든다. **상위 표기와 하위 표기를 구분해야 한다.**

- `req(symbol)`의 `symbol`은 **상위 표기** — 원천 generator가 아는 심볼(`"BTC/USD"`).
- bind 콜백이 받는 `symbol`은 **하위 표기** — 소비자가 구독한 심볼(`"BTC"`).
- 둘이 달라도 되게 하는 것이 이 모델의 존재 이유다. 상·하위가 같은 요청으로만 시험하면
  둘을 뒤바꾼 버그가 드러나지 않는다.

주의할 점:

- **상위 스테이지에 등록하는 심볼은 `reg.router.symbols`**, 즉 시퀀스가 요구한 상위 표기다.
  스테이지가 받은 하위 심볼이 아니다.
- **`"__require__"`는 슬롯 키 센티널**이다. `req_cb`가 만든 슬롯이라 `bind_cb`가 연 적이 없고,
  따라서 `unbind_cb`도 부르지 않는다. `update()`의 `del_symbols`에도 `detach()`의 unbind 대상에도
  들어가지 않는다. 반대로 이 센티널이 실제 심볼 계산(`new_symbols`)에 섞이면 binder가 그것을
  심볼인 양 받는다.
- **`SendRouterSet`은 content_id별로 `SendRouter` 하나를 유지한다.** `clear()`는 라우터만 비우고
  `Registered` 항목은 남긴다 — 같은 content_id에 같은 `SendRouter` **객체**가 유지되어야 스테이지에
  등록된 `Sender`와의 동일성 검사가 깨지지 않는다.
- 데이터 흐름: 원천 → `SendRouter`(상위 표기로 라우팅) → `SequenceSender` → 슬롯의 `TransmitQueue`
  → `_task_sequence()`가 `seq.invoke()`를 거쳐 소비자에게 보낸다.

### TaskManager (helper.py)

`Domain`의 모든 generator 루프는 `TaskManager.submit(coro, name)`으로 실행된다. 이름이 태스크의
정체성이며 **대기 중에도 이름이 점유**된다. `cancel_by_name()`은 실행 중이면 취소 후 `gather`로,
큐 대기 중이면 `_cancelled_pending`에 예약한 뒤 release 이벤트로 **이름 해제까지 기다린다**.
이 대기가 없으면 `Domain`이 같은 이름으로 재제출할 때 이름 충돌이 난다.

`TaskManager`와 예제 binder는 진단용 `print`를 그대로 출력한다(`[TASK SUBMIT]` 등).

## 코드 규약

- Python **3.14** 전용. PEP 695 제네릭 문법(`class Stage[T: BaseReqModel]`, `type X = ...`)을 사용하고
  `TypeVar`를 새로 도입하지 않는다.
- ruff: line-length 100, rules `E,F,I,UP,B`. pyright `standard`, `src`/`tests`/`examples` 포함.
- 런타임 의존성은 pydantic 하나뿐이다. 새 런타임 의존성을 추가하기 전에 확인할 것.
- 커밋 메시지는 Conventional Commits(`feat:`, `fix:`, `docs:`)를 쓴다.
- `async for x in cb(...): yield x` 형태로 async generator를 감쌀 때는 `contextlib.aclosing`으로
  감쌀 것. 그러지 않으면 바깥을 `aclose()`해도 **안쪽 generator의 `finally`가 돌지 않는다.**

## 테스트

테스트는 예제를 import하지 않는다. 예제는 발행 간격이 0.5초라 느리고, 예제를 고치면 테스트가
같이 깨지기 때문이다. 대신 `tests/support/streams.py`에 **테스트 전용 요청·binder**를 두고
발행 간격을 0.01초로 잡았다.

| 파일 | 덮는 범위 |
| --- | --- |
| `tests/support/streams.py` | 테스트 전용 모델·binder(원천 · 파생 · 심볼 변환 파생 · instanter 둘)와 스테이지 사건 기록 |
| `tests/support/harness.py` | `Recorder`(Sender 구현), `wait_until()` |
| `tests/conftest.py` | `domain` 픽스처(시작 → 테스트 → `stop()`) |
| `tests/test_model.py` | 식별자 3종, content_id 캐시 무효화, `validate_model`·`cast_model` 왕복, `Sequence` |
| `tests/test_helper.py` | digest/id, `TaskManager` 이름 점유·취소·재사용·실패 콜백 |
| `tests/test_binder.py` | `initialize()` 추론과 거부 규칙, require 두 형태, 재바인드 거부, 전역 레지스트리 |
| `tests/test_transport.py` | `TransmitQueue`, `SendRouter` 라우팅·교체·해제 |
| `tests/test_domain.py` | content_id 단위 공유, 심볼 합집합, 재시작 조건, 두 정리 지점, 의존 스트림, instanter |

옛 테스트를 되살리지 말 것 — 참고할 일이 있으면 `ff64509` 이전 이력에서 꺼내 보면 된다.
ex05가 남긴 "파생 스테이지가 상위에 등록하는 심볼은 구독자 전체의 합집합"이라는 불변식은
`test_dependent_registers_the_union_upstream`이 덮는다(내력은 `1510812` 참고).

"합집합이 그대로면 재시작하지 않는다"는 규칙은 두 분기 모두 덮여 있다. 원천 분기는
`test_origin_restarts_only_when_the_union_changes`가, 파생 분기는
`test_dependent_restarts_only_when_the_union_changes`가 맡는다. 후자는 ex06과 같은 시나리오이며,
`domain.py`의 dependent 조기 반환을 지우면 이 테스트만 깨진다.

instanter 경로는 `test_domain.py`의 `instanter 스트림` 절이 덮는다. 상·하위 표기 혼동은
`test_instant_stage_maps_symbols_to_the_upstream`이, bind↔unbind 짝은
`test_instant_unbinds_each_symbol_exactly_once`가, 센티널 취급은
`test_instant_require_slot_is_not_unbound`가 맡는다. 이 셋은 상·하위 표기가 **다른** 요청
(`SwingReq`: `BTC` → `BTC/USD`)을 쓰기 때문에 성립한다 — 같은 표기로 바꾸면 못 잡는다.

"content_id가 같아도 요청형 스테이지는 공유되지 않는다"는 ex08과 같은 시나리오인
`test_equal_instant_requests_do_not_share_a_stage`가 맡는다. 원천 쪽 짝인
`test_equal_requests_share_one_origin_stage`와 나란히 읽으면 공유의 경계가 보인다.
`_define_stage()`에서 instanter를 content_id로 캐시하도록 바꾸면 이 테스트만 깨진다.

테스트를 더 쓸 때 걸리는 제약:

- `asyncio_mode = "auto"`이므로 async 테스트에 `@pytest.mark.asyncio`가 필요 없다.
- `BindPack._binder_dict`가 **프로세스 전역**이라 같은 요청 타입을 두 번 등록하면 `BindError`가 난다.
  그래서 binder는 모듈 수준에서 한 번만 등록하고, 테스트끼리는 요청의 `tag` 필드 값을 달리해
  **서로 다른 content_id = 서로 다른 스테이지**로 격리한다. 같은 `tag`를 두 테스트가 쓰면 스테이지와
  기록을 공유하게 된다.
- generator (재)시작은 `TaskManager.submit()`을 거치므로 `update()` 직후에는 아직 실행되지 않았다.
  "재시작했다"는 `wait_until()`로 기다려 확인하고, 동기적으로 단정할 수 있는 것은 `SendRouter`에
  등록된 심볼(`origin.output.symbols`)뿐이다. instanter의 `unbind_cb`는 예외로, `update()`가
  `TaskGroup`으로 await하므로 반환 직후에 단정할 수 있다.
- binder는 무한히 데이터를 발행하므로 소비 개수나 `Recorder.wait_for()`로 종료를 제어해야 한다.
- 새 불변식을 테스트로 덮었으면 **수정을 되돌려 그 테스트만 깨지는지** 확인할 것. 안 깨지면
  테스트가 그 불변식을 못 덮고 있는 것이다.
