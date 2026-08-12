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
uv run pytest                # 테스트 (현재 테스트가 하나도 없다 — "테스트" 절 참고)
```

코드 변경 후 위 4개(check / format / pyright / pytest)가 모두 통과해야 한다. 지금은 앞의 셋이
클린이고 `pytest`는 수집할 테스트가 없어 exit 5("no tests ran")를 낸다. 이 상태에서는 **예제 실행이
사실상의 회귀 검증**이므로, `src/`를 고쳤으면 `uv run examples/main.py serial`까지 돌려 볼 것.

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

등록 API 리팩터링(`definer.py` → `binder.py`)은 **끝났고 `main`에 들어가 있다.** 작업 브랜치였던
`update/require`는 `main`과 같은 커밋이 되어 삭제했으므로, 이제 브랜치는 `main` 하나뿐이다.
아래는 2026-08-12 기준이며, 코드(`src/` · `examples/`)는 완료 상태이고 **남은 것은 테스트와 문서뿐이다.**

- `src/trading_core/definer.py`(옛 `@generator` / `@task` / `@processor` 레지스트리)는 **삭제**되었고
  `src/trading_core/binder.py`(`initialize()` 기반)로 대체되었다. 코드에는 옛 API 참조가 하나도 없다.
- 마이그레이션 완료: `src/trading_core/**`, `examples/ex01`~`examples/ex05`(다섯 예제 모두 실행된다).
- **`tests/` 디렉터리 자체가 없다.** 옛 API에 묶인 테스트를 마이그레이션하는 대신 전부 삭제했고,
  새 API 기준으로 처음부터 다시 쓸 예정이다. 무엇을 덮고 있었는지는 아래 "테스트" 절에 남겨 뒀다.
- `uv run ruff check` · `ruff format --check` · `pyright` **모두 클린이다**(pyright 0 errors).
  단 `pyright`는 `tests` 디렉터리가 없다는 안내를 한 줄 찍고, `pytest`는 수집 대상이 없어 exit 5를 낸다.
  둘 다 `pyproject.toml`이 아직 `tests`를 가리키기 때문이며, 테스트를 다시 쓰면 자연히 사라진다.
- `README.md`는 옛 API(`@generator` / `.bind` / `.close` / `definer.py`)를 그대로 설명한다.
  개념 설명(공유 · fan-out · 수명 주기)은 여전히 정확하지만 **코드 예제와 API 이름은 신뢰하지 말 것**.
  `examples/ex01/README.md`도 같은 상태이고, ex02~ex05의 README는 새 API 기준이다.
- `TODO.md`에 남은 과제와 이미 해결한 불변식의 내력이 적혀 있다. 특히 "require 콜백이 심볼에 따라
  다른 상위 요청을 반환할 수 없다"는 제약은 현재 구조상 유효하다.
- `playground.py`는 타입 실험용 스크래치 파일이다. 정식 예제가 아니다.

## 아키텍처

### 레이어

| 파일 | 책임 |
| --- | --- |
| `model.py` | `TrBaseModel` 계열 요청/데이터 모델, 3종 식별자, 직렬화·검증, `Sequence` |
| `binder.py` | `initialize()` 데코레이터와 `BindPack` 전역 레지스트리 (요청 타입 → 콜백) |
| `domain.py` | `Domain`, `Stage`/`OriginGenStage`, `SharedSender`, `TransmitQueue`, 수명 주기 |
| `helper.py` | digest/id 생성, 이름 기반 취소를 지원하는 비동기 `TaskManager` |
| `exceptions.py` | 프레임워크 예외 |

### 모델 계층

`TrBaseModel`(pydantic `BaseModel`) 아래에 요청 계열과 데이터 계열이 나뉜다.

```
TrBaseModel
├── BaseReqModel          (_tr_model_type = "unregistered")
│   ├── GenerateModel     → 바인드되면 "generator"
│   ├── DependentModel    → 바인드되면 "dependent_generator"  (require로 상위 요청 선언)
│   └── RequestModel      → 바인드되면 "request"
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
- `DependentModel`은 generate 콜백을 바인드하기 **전에** require를 선언해야 한다:

  ```python
  @NamingReq.require(origin.NamingAllReq)
  def _(req: NamingReq) -> origin.NamingAllReq:
      return origin.NamingAllReq()
  ```

- dependent binder의 시그니처는 `(ctx, symbols, recv: Receiver)`로 인자가 하나 더 많다.
  `recv()`로 상위 원천 데이터를 받아 `cast_model()`로 좁혀 쓴다.
- `BindPack._binder_dict`는 **프로세스 전역 클래스 변수**다. 같은 `model_id`를 두 번 등록하면
  `BindError`가 난다. 테스트에서 예제 모듈을 여러 번 import해도 등록은 한 번뿐이라는 전제를 갖는다.

### 실행 (domain.py)

핵심 불변식:

1. **content_id 단위 공유** — `_origin_stage_dict[content_id]`에 origin stage가 하나만 존재한다.
   여러 소비자가 같은 요청을 보내면 컨텍스트와 generator를 공유한다.
2. **심볼 합집합** — `SharedSender`가 (Sender, symbols) 쌍을 모으고, binder에는 **합집합**만 넘긴다.
   출력은 `data.symbol`을 구독한 Sender에게만 fan-out된다.
3. **합집합이 바뀔 때만 재시작** — `update()`는 `current_symbols == active_symbols`면 즉시 반환한다.
   달라지면 이름으로 태스크를 취소하고 `gen.aclose()` 후 새 generator를 만든다.
4. **두 개의 정리 지점** — binder의 `finally`는 *구독 업데이트 단위* 정리, `@x.detached`는
   *스테이지 전체* 정리다. 합집합이 빈 집합이 되면 stage를 dict에서 제거하고 detach 콜백을 부른다.
5. **`update(symbols)`는 교체이지 추가가 아니다.** 빈 집합을 넘기면 그 소비자의 구독이 사라진다.

두 가지 소비 API:

- `Domain.request(req, symbols)` — 내부에서 `TransmitQueue`와 Stage를 만들어 async generator를 준다.
  `aclosing`으로 감싸져 있어 조기 `break`에도 구독이 정리된다.
- `Domain.stage(req, sender)` — 호출자가 `Sender`를 제공하고 `stage.update(symbols)`로 실행 중
  심볼 집합을 교체하는 저수준 API.

의존 스트림은 `_ensure_require_stage()`가 상위 요청의 origin stage를 만들거나 재사용하고,
`TransmitQueue`로 상위 출력을 하위 binder의 `recv`에 연결한다. 상위 원천도 동일하게 content_id와
합집합 기준으로 공유된다. 순환 의존은 지원하지 않는다.

`Stage`는 `_STAGE_CREATION_KEY` 가드로 `Domain`을 통해서만 생성된다.

### TaskManager (helper.py)

`Domain`의 모든 generator 루프는 `TaskManager.submit(coro, name)`으로 실행된다. 이름이 태스크의
정체성이며 **대기 중에도 이름이 점유**된다. `cancel_by_name()`은 실행 중이면 취소 후 `gather`로,
큐 대기 중이면 `_cancelled_pending`에 예약한 뒤 release 이벤트로 **이름 해제까지 기다린다**.
이 대기가 없으면 `Domain`이 같은 이름으로 재제출할 때 이름 충돌이 난다.

`TaskManager`와 예제 binder는 진단용 `print`를 그대로 출력한다(`[TASK SUBMIT]` 등).
`binder.initialize()`에도 디버그 `print(type_hints)`가 남아 있다.

## 코드 규약

- Python **3.14** 전용. PEP 695 제네릭 문법(`class Stage[T: BaseReqModel]`, `type X = ...`)을 사용하고
  `TypeVar`를 새로 도입하지 않는다.
- ruff: line-length 100, rules `E,F,I,UP,B`. pyright `standard`, `src`/`tests`/`examples` 포함.
- 런타임 의존성은 pydantic 하나뿐이다. 새 런타임 의존성을 추가하기 전에 확인할 것.
- 커밋 메시지는 Conventional Commits(`feat:`, `fix:`, `docs:`)를 쓴다.

## 테스트

**현재 테스트가 하나도 없다.** `tests/`는 디렉터리째 삭제했고, 새 API(`initialize()` 기반 binder)
기준으로 처음부터 다시 작성할 계획이다. 옛 테스트를 되살리지 말 것 — 참고할 일이 있으면
`ff64509` 이전 이력에서 꺼내 보면 된다.

지워진 테스트가 덮던 범위(다시 쓸 때의 출발점):

- **프레임워크 단위 명세** — 모델 식별자 3종, `SharedSender` 라우팅, 원천 공유·재시작 조건,
  `TaskManager` 이름 기반 취소.
- **모델 직렬화** — `validate_model` · `cast_model` 왕복.
- **예제 기반 명세** — ex01~ex03, ex05를 실행 가능한 명세로 검증했다. ex04는 대응 테스트가 없었다.
  특히 ex05는 "파생 스테이지가 상위에 등록하는 심볼은 구독자 전체의 합집합"이라는 불변식의
  회귀 테스트였다(`1510812` 참고). **이 불변식은 다시 덮는 것이 좋다.**

새로 쓸 때 걸리는 제약:

- `asyncio_mode = "auto"`이므로 async 테스트에 `@pytest.mark.asyncio`가 필요 없다.
- `BindPack._binder_dict`가 **프로세스 전역**이라 같은 요청 타입을 두 번 등록하면 `BindError`가 난다.
  예제 모듈을 import해 쓰는 테스트는 "등록은 프로세스당 한 번"이라는 전제 위에서 짜야 하고,
  binder를 호출해 컨텍스트를 만들려 들면 그 호출이 곧 재바인딩이라 실패한다(옛 테스트가 깨진 원인).
- 예제 binder는 무한히 데이터를 발행하므로 소비 개수나 이벤트로 종료를 제어해야 한다.
  예제의 발행 간격은 0.5초다.
- 예제를 고치면 대응 테스트도 함께 깨진다는 점은 그대로다.
