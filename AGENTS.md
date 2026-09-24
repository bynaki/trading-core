# AGENTS.md

이 저장소에서 일하는 코딩 에이전트(Claude Code 등)를 위한 안내서다. `CLAUDE.md`는 이 파일을 참조만 한다.

## 프로젝트 개요

`trading-core`는 특정 거래소에 종속되지 않은 **타입 안전 비동기 스트리밍 오케스트레이션 코어**다.
WebSocket 클라이언트가 아니라, 실시간 스트림을 다룰 때 반복되는 요청 모델링 · 구독 공유 ·
심볼별 라우팅 · 의존 스트림 연결 · 태스크 수명 주기를 제공하는 런타임이다. 거래소별 인증 ·
구독 · 파싱은 사용자가 binder로 구현한다.

문서·주석·docstring·예외 메시지는 **한국어**로 작성한다. 기존 스타일을 따를 것.

## 새 세션을 시작할 때

- 이 파일 다음으로 **`docs/TODO.md`**(세션을 넘어 남는 백로그)를 읽는다. 새로 안 것·남긴 후속
  작업은 `TODO.md`에 적는다.
- **`docs/HANDOFF.md`는 있을 때만 읽는다.** 직전 세션이 멈춘 곳을 넘기는 일회성 문서라 평소엔 없다.
  이어받아 끝내면 지운다.
- `TODO.md` 항목은 `### [done] <prefix>:<word>` 제목 아래 내용을 적는다. `<prefix>:<word>`
  (예: `logger:server-transport`)가 항목 구분자이자 태그이고, 같은 `prefix`는 같은 주제다.
- 할 일을 마치면 그 자리에서 제목에 `[done]`만 붙인다. `docs/DONE.md`로 옮기는 것은 커밋 때다
  (아래 "코드 규약"의 커밋 절차).
- `docs/DONE.md`는 열린 항목과 더 이상 관련 없는 완료 항목의 아카이브다. 매번 읽지 않고, 내력이
  필요할 때 태그로 찾아본다.
- `HANDOFF.md`·`TODO.md`에는 **git 상태를 적지 않는다**(커밋 해시, 앞선 커밋 수, 원격·PR·병합
  여부). 적는 순간 틀린 말이 된다. `git status`·`git log`로 확인한다.

## 환경

- Python **3.14** (`.python-version`, uv가 자동 인식)
- 런타임 의존성: **pydantic** 하나뿐
- 개발 도구: ruff(린트+포맷) · pyright(타입) · pytest(테스트)

## 명령

모든 명령은 `uv`로 실행한다(`uv run`이 프로젝트 `.venv`를 쓰므로 `activate` 불필요).

```bash
uv run ruff check .          # 린트
uv run ruff format .         # 포맷 적용
uv run ruff format --check . # 포맷 검사
uv run pyright               # 타입 체크 (standard)
uv run pytest                # 테스트 (약 0.5초)
```

**작업을 마쳤을 때 소스코드(`src/`·`tests/`·`examples/`)를 고쳤다면** 위 4개(check / format --check /
pyright / pytest)를 모두 통과시킨다. 문서만 고쳤으면 돌리지 않는다. 커밋 절차에는 들어가지 않는다.
테스트는 예제를 돌리지 않으므로 `src/`를 고쳤으면 `uv run examples/main.py serial`도 돌려 볼 것.

```bash
uv run python examples/ex01/run_ex.py # 예제 파일을 직접 실행 (자체 Domain을 만든다)
uv run examples/main.py ex01          # 예제 이름으로 실행
uv run examples/main.py serial        # 모든 예제를 공유 Domain에서 순차 실행
uv run examples/main.py parallel      # 모든 예제를 공유 Domain에서 동시 실행
```

`examples/main.py`는 `examples/*/run_ex.py`를 글롭으로 찾는다 — `run_ex(domain)` 코루틴을 가진
디렉터리를 추가하면 자동으로 포함된다. 의존성: `uv add <pkg>`(런타임) / `uv add --dev <pkg>`(개발).

## 저장소 메모

- `README.md`는 **의도적으로 얇다** — 소개·설치·예제 실행법·범위와 한계만 둔다. API가 아직
  자리 잡는 중이라 **코드 예제와 API 이름을 넣지 않는다.** 사용법은 실행되는 `examples/`가 맡는다.
- 예제를 고치면 같은 디렉터리의 README도 함께 고친다.
- 운영·설계 문서는 `docs/`에 있다: `TODO.md`, `DONE.md`, `design.log.md`(로그 모듈 설계),
  `design.naming.md`(이름 정리 내역), 있을 때만 `HANDOFF.md`.
- 예제는 ex01~ex09. ex06은 파생 스테이지의 "합집합이 그대로면 재시작 안 함", ex07·ex08은
  세션 요청(ex08은 세션 스테이지가 content_id로 공유되지 **않음**), ex09는 로그 모듈이다.
- 예제 출력은 모두 `trading_core.logger`로 남긴다(`print` 없음). 공용 설정은
  `examples/setting.toml`이고 `main.py`와 각 `run_ex.py`의 `main()`이 `configure()`한다. 로거
  이름은 `__name__`이 아니라 `"ex05.origin"`처럼 직접 준다 — 직접 실행하면 `__main__`이 되어 어느
  예제인지 안 보인다. `get_logger(__name__)` 관용구를 보이는 ex09만 예외다.
- ex09만 자기 `setting.toml`로 재구성했다가 끝에 공용 설정으로 **다시 `configure()`해** 되돌린다.
  `shutdown()`하면 그 뒤로 도는 예제의 로그가 어디로도 안 나간다.
- `playground.py`는 타입 실험용 스크래치 파일이다. 정식 예제가 아니다.

## 아키텍처

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
│   ├── SourceRequest      → 바인드되면 "source"   (원천)
│   ├── DerivedRequest     → 바인드되면 "derived"  (파생. require로 상위 요청 선언)
│   └── SessionRequest     → 바인드되면 "session"  (세션. 상태를 가져 공유하지 않음)
└── DataModel              (_tr_model_type = "data", symbol: str 라우팅 키)
```

`_tr_model_type`은 `BindPack.set_*_cb()`가 실행될 때 기록된다 — **모듈이 import되어 데코레이터가
실행되어야** 요청을 쓸 수 있다. `Domain`은 이 값으로 스테이지 종류를 고른다. 이 값은 직렬화되어
`tr_annotation.model_type`에 실린다.

식별자 3종은 역할이 다르다.

- **uid** (`_tr_uid`, `get_model_uid`): `클래스@모듈:인스턴스ID:순번`. 개별 모델 추적용. 인스턴스 ID는
  모델을 만든 프로세스의 것(`set_instance_id`/`get_instance_id`, `get_model_created_by`)이다. 기본값은
  로그 발신처 `instance_id`(`service@host:pid`, `logger.get_identity()`)에 6자리 무작위 꼬리를 붙인
  것이라 `@`·`:`가 들어 있다 — uid를 구분자로 쪼개지 말 것. 처음 만든 모델이 값을 정하므로
  `service_name`을 바꿔 `configure()`하려면 모델을 만들기 전에 한다.
- **model_id** (`get_model_id`): `클래스@모듈:필드이름구조digest`. binder 레지스트리 키이자
  `cast_model()`의 일치 기준(상속이 아니라 정확한 일치).
- **content_id** (`tr_content_id`): 모델 타입 + JSON 직렬화 내용의 digest. **공유의 기준**. 캐시하며,
  필드를 골라 계산하려면 `compute_tr_content_id(include, exclude)`를 쓴다.

모델은 **가변**이고 `__setattr__`이 content_id 캐시를 무효화한다. 그래서 hashable이 아니다 —
`set`·dict 키로 쓰지 말고 content_id를 키로 쓴다. 직렬화 시 `tr_annotation`이 붙고,
`load_model()`은 그 `module_name`/`model_name`으로 클래스를 되찾아 복원한다(`parse_dump()`는 덤프만
검증한다).

### 등록 (binder.py)

```python
@initialize                      # init 콜백의 첫 파라미터 어노테이션으로 요청 타입을 추론
def naming(req: NamingAllReq) -> NamingAllContext:
    return NamingAllContext(req)  # content_id 수명 동안 공유되는 컨텍스트

@naming                          # SourceBinder.__call__ → generate 콜백
async def _(ctx: NamingAllContext, symbols: set[str]):
    yield NamingAllData(...)

@naming.detached                 # 마지막 구독이 사라질 때 컨텍스트 정리
async def _(ctx: NamingAllContext): ...
```

- `initialize()`는 `get_type_hints(cb)`의 **첫 값**을 요청 타입으로 쓴다(어노테이션 필수). 요청 타입에
  따라 `SourceBinder` / `DerivedBinder` / `SessionBinder`를 반환한다.
- `DerivedRequest`는 **인자 없는** 데코레이터 `require`로 상위 요청을 선언한다. 두 형태를 받고
  위치 인자 개수로 구분해 `RequireCbWithSym`으로 정규화한다(`resolve_upstream(symbols)`로 꺼낸다).
  require 없이 파생 스테이지를 만들면 `ModelError`.

  ```python
  @NamingReq.require                    # RequireCb — 요청만 받는다
  def _(req: NamingReq) -> origin.NamingAllReq:
      return origin.NamingAllReq()

  @PriceRequest.require                 # RequireCbWithSym — 심볼까지 변환한다
  def _(req: PriceRequest, symbols: set[str]):
      return origin.TickReq(), {f"{s}/USD" for s in symbols}
  ```

- 파생 binder는 `(ctx, symbols, recv: Receiver)` — `recv()`로 상위 데이터를 받아 `cast_model()`로 좁힌다.
- `SessionRequest`는 `@x`(bind) · `@x.unbind` · `@x.always` · `@x.detached`를 붙인다. bind와 always는
  하나씩만 등록되고 두 번째는 `BindError`. 파생의 `require`(상위 요청 선언)와 세션의 `always`(늘 붙는
  파이프라인)는 다른 것이다.
- `BindPack._registry`는 **프로세스 전역**이다(`BindPack.lookup(model_id)`). 같은 `model_id`를 두 번
  등록하면 `BindError`.

### 실행 (domain.py)

핵심 불변식:

1. **content_id 단위 공유** — 원천·파생은 `_shared_stages[content_id]`에 `SharedStage`가 하나만 있다.
   같은 요청의 소비자들은 컨텍스트와 generator를 공유한다. 세션 요청은 공유하지 않는다.
2. **심볼 합집합** — `SymbolRouter`가 (Sender, symbols)를 모아 binder에는 **합집합**만 넘기고,
   출력은 `data.symbol`을 구독한 Sender에게만 fan-out한다.
3. **합집합이 바뀔 때만 재시작** — `current_symbols == active_symbols`면 `update()`는 즉시 반환한다.
   달라지면 태스크를 이름으로 취소하고 `gen.aclose()` 후 새 generator를 만든다(원천·파생 한정).
4. **두 개의 정리 지점** — binder의 `finally`는 구독 업데이트 단위, `@x.detached`는 스테이지 전체.
   합집합이 비면 스테이지를 dict에서 빼고 detach 콜백을 부른다.
5. **`update(symbols)`는 교체다**(`SymbolRouter.replace()`). 빈 집합을 넘기면 그 소비자의 구독이 사라진다.
6. **bind ↔ unbind 짝** — 세션에서 `bind_cb`로 연 심볼은 `update()`로 빠지든 `detach()`로 닫히든
   `unbind_cb`가 **정확히 한 번** 불린다(`unbind_symbols()` 공유). 슬롯 닫기(`close_slots()`)는 슬롯
   태스크의 이름 해제까지 기다린다.

소비 API: `Domain.stream(req, symbols)`는 async generator를 준다(`aclosing`으로 감싸 조기 `break`에도
정리). `Domain.subscribe(req, sender)`는 호출자가 `Sender`를 주고 `sub.update(symbols)`로 심볼을
교체하는 저수준 API다(`Subscription`을 준다). `get_shared_symbols(content_id)`는 공유 중인 스테이지의
심볼 합집합을 돌려준다(공유 중이 아니면 빈 집합). `Subscription`·`SharedStage`는 `_STAGE_CREATION_KEY`
가드로 `Domain`을 통해서만 만들어진다. 공개 API는 작게 두고 내부 객체(스테이지)를 돌려주지 않는다.

의존 스트림: `_ensure_upstream_stage()`가 상위 `SharedStage`를 만들거나 재사용하고 `Channel`로
하위 binder의 `recv`에 잇는다. 상위도 content_id·합집합 기준으로 공유된다. 순환 의존은 지원하지 않는다.
파생 스테이지는 상위 하나만 바라보므로 **require 콜백이 심볼에 따라 다른 상위 요청을 반환할 수 없다.**

#### 세션 (SessionRequest)

원천·파생이 "심볼 집합 하나 → generator 하나"라면, 세션은 **심볼마다 슬롯 하나**를 만들고 각
슬롯이 `Pipeline`으로 상위 원천에 붙는다(`Domain._create_session_subscription()`, 예: ex07, 테스트의
`SwingReq`). 차트 분석처럼 상태를 가지므로 content_id가 같아도 공유하지 않는다(ex08).

```python
@swing                                   # bind — 심볼 하나의 Pipeline을 yield
async def _(ctx: SwingCtx, symbol: str):
    yield TickReq()(f"{symbol}/USD") | SwingRunnable(symbol)

@swing.unbind                            # 그 심볼의 슬롯이 닫힐 때
async def _(ctx: SwingCtx, symbol: str): ...

@swing.always                            # 구독 심볼과 무관하게 늘 붙는 Pipeline
async def _(ctx: SwingCtx):
    yield TickReq()("HEARTBEAT/USD") | ...
```

**상위 표기와 하위 표기를 구분한다.** `req(symbol)`의 `symbol`은 상위 표기(원천이 아는 `"BTC/USD"`,
`Pipeline.upstream_symbol`), bind 콜백이 받는 `symbol`은 하위 표기(소비자가 구독한 `"BTC"`)다.
상·하위가 같은 요청으로만 시험하면 둘을 뒤바꾼 버그가 안 드러난다.

- 상위 구독에 등록하는 심볼은 `route.router.symbols`(상위 표기)다. 하위 심볼이 아니다.
- `_ALWAYS_SLOT`(`"__always__"`)은 `always_cb` 슬롯의 키 센티널이다. bind된 적이 없으므로 `unbind_cb`
  대상이 아니고, 실제 심볼 계산에 섞여서도 안 된다.
- `UpstreamRouters`는 content_id별로 `SymbolRouter` **객체** 하나를 유지한다(`Sender` 동일성 검사 때문).
  `clear()`는 라우터만 비우고, 다시 채운 뒤 `prune()`이 센더 없는 항목을 지우며 그 상위 구독을
  같은 `update()`에서 떼어 낸다.
- 데이터 흐름: 원천 → `SymbolRouter`(상위 표기) → `PipelineSender` → 슬롯 `Channel` →
  `_run_pipeline_slot()`이 `pipeline.invoke()`를 거쳐 소비자에게.
- 슬롯은 상위 구독 갱신보다 먼저 닫히므로, 닫힌 슬롯으로 온 데이터의 `ChannelClosed`는
  `PipelineSender`가 삼킨다. 올려 보내면 공유된 상위 generator가 죽는다.

### TaskManager (tasks.py)

`Domain`의 generator 루프는 모두 `TaskManager.submit(coro, name)`으로 돈다. 이름이 태스크의 정체성이고
**대기 중에도 점유**된다. `cancel_by_name()`은 실행 중이면 취소 후 `gather`, 대기 중이면
`_cancelled_pending`에 예약하고, 어느 쪽이든 **이름 해제까지 기다린다**(안 그러면 같은 이름 재제출이
충돌한다). `live_count`는 끝나지 않은(대기 + 실행) 태스크 수다. 제출·완료·취소·예외 훅은 `logger.py`로
DEBUG 로그를 남긴다.

## 코드 규약

- Python **3.14** 전용. PEP 695 제네릭 문법(`class Subscription[T: BaseRequest]`, `type X = ...`)을 쓰고
  `TypeVar`를 새로 도입하지 않는다.
- ruff: line-length 100, rules `E,F,I,UP,B`. pyright `standard`, `src`/`tests`/`examples` 포함.
- 런타임 의존성은 pydantic 하나뿐이다. 새 런타임 의존성을 추가하기 전에 확인할 것.
- 커밋 메시지는 Conventional Commits(`feat:`, `fix:`, `docs:`)를 쓴다.
- **커밋은 사용자가 요청하고 승인했을 때만 한다.** 절차는 프로젝트 스킬
  `.claude/skills/commit/SKILL.md`(`/commit`)를 따른다: TODO→DONE 이관 → 개인정보·보안 검사 →
  보고·승인 → 커밋. 스킬을 쓸 수 없는 에이전트도 이 파일을 읽고 같은 순서를 지킨다.
- `async for x in cb(...): yield x`로 async generator를 감쌀 때는 `contextlib.aclosing`으로 감싼다.
  안 그러면 바깥을 `aclose()`해도 **안쪽 generator의 `finally`가 돌지 않는다.**

## 테스트

테스트는 예제를 import하지 않는다(예제는 발행 간격 0.5초로 느리고, 예제를 고치면 테스트가 깨진다).
대신 `tests/support/streams.py`에 발행 간격 0.01초의 **테스트 전용 요청·binder**를 둔다.

| 파일 | 덮는 범위 |
| --- | --- |
| `tests/support/streams.py` | 테스트 전용 모델·binder(원천 · 파생 · 심볼 변환 파생 · 세션 셋)와 스테이지 사건 기록 |
| `tests/support/harness.py` | `Recorder`(Sender 구현), 느린 소비자 `BlockingRecorder`, `wait_until()` |
| `tests/conftest.py` | `domain` 픽스처(시작 → 테스트 → `stop()`) |
| `tests/test_model.py` | 식별자 3종, content_id 캐시 무효화, `load_model`·`cast_model` 왕복, `Pipeline` |
| `tests/test_ids.py` | digest/id 생성, 정의 모듈 찾기 |
| `tests/test_tasks.py` | `TaskManager` 이름 점유·취소·재사용·실패 콜백 |
| `tests/test_binder.py` | `initialize()` 추론과 거부 규칙, require 두 형태, 재바인드 거부, 전역 레지스트리 |
| `tests/test_routing.py` | `Channel`, `SymbolRouter` 라우팅·교체·해제, 닫힌 슬롯의 `PipelineSender` |
| `tests/test_logger.py` | 설정 탐색·검증, JSON 레코드·발신처, 싱크별 레벨, 파일 회전, 재구성·종료 |
| `tests/test_domain.py` | content_id 단위 공유, 심볼 합집합, 재시작 조건, 두 정리 지점, 의존 스트림, 세션 |

잘 깨지지 않는 불변식과 그것을 덮는 테스트(고칠 때 이 테스트가 깨지는지 본다):

| 불변식 | 테스트 | 주의 |
| --- | --- | --- |
| 파생이 상위에 등록하는 심볼 = 구독자 합집합 | `test_dependent_registers_the_union_upstream` | |
| 합집합이 그대로면 재시작 안 함 | `test_origin_restarts_only_when_the_union_changes`, `test_dependent_restarts_only_when_the_union_changes` | 후자는 ex06 시나리오 |
| 상·하위 표기 매핑 | `test_session_stage_maps_symbols_to_the_upstream` | 표기가 **다른** `SwingReq`(`BTC`→`BTC/USD`)라야 잡힌다 |
| bind↔unbind 정확히 한 번 | `test_session_unbinds_each_symbol_exactly_once` | 〃 |
| 센티널 슬롯은 unbind 안 함 | `test_session_always_slot_is_not_unbound` | 〃 |
| 빼자마자 재구독 가능 | `test_session_symbol_can_be_resubscribed_right_away` | `BlockingRecorder`로 슬롯 태스크를 묶어야 드러난다 |
| 안 쓰이는 상위를 떼어 냄 | `test_session_detaches_an_upstream_no_pipeline_uses` | 심볼마다 다른 상위를 드는 `SplitReq` |
| 닫힌 슬롯이 상위를 죽이지 않음 | `test_pipeline_sender_drops_data_for_a_closed_slot` | 경합이라 단위 테스트로 고정 |
| 세션 스테이지는 content_id로 공유 안 함 | `test_equal_session_requests_do_not_share_a_stage` | ex08 시나리오. 짝: `test_equal_requests_share_one_stage` |

테스트를 쓸 때 걸리는 제약:

- `asyncio_mode = "auto"` — `@pytest.mark.asyncio`가 필요 없다.
- binder 레지스트리가 프로세스 전역이라 binder는 모듈 수준에서 한 번만 등록한다. 테스트끼리는 요청의
  `tag` 값을 달리해 **다른 content_id = 다른 스테이지**로 격리한다(같은 `tag`면 스테이지·기록 공유).
- generator (재)시작은 `TaskManager.submit()`을 거쳐 `update()` 직후엔 아직 안 돌았다. 재시작은
  `wait_until()`로 확인하고, 동기로 단정할 수 있는 건 `domain.get_shared_symbols()`뿐이다. 예외로 세션의
  `unbind_cb`는 `update()`가 await하므로 반환 직후 단정할 수 있다.
- binder는 무한히 발행하므로 소비 개수나 `Recorder.wait_for()`로 끝낸다.
- `test_logger.py`는 전역 루트 로거를 건드린다. autouse 픽스처가 CWD·환경변수를 격리하고 `shutdown()`으로
  되돌린다. 레코드는 파일 싱크를 켜고 `shutdown()`으로 큐를 비운 뒤 읽는다(리스너 스레드가 쓴다).
- 새 불변식을 테스트로 덮었으면 **수정을 되돌려 그 테스트만 깨지는지** 확인한다.
