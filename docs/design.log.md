# 로그 모듈 설계 (`logger.py`)

`docs/TODO.md` 10번 과제의 설계 문서다. 구현은 `src/trading_core/logger.py`, 명세는
`tests/test_logger.py`에 있다. 구현하면서 정한 것(자동 구성 시점, `shutdown()` 뒤의 동작, 로그서버
싱크 뼈대의 범위)도 이 문서에 반영했다.

## 1. 목적과 범위

프로젝트 전반(`domain.py`, `helper.py`, 그리고 이 코어를 쓰는 바깥 앱)에서 공통으로 쓸 로그 모듈이다.
콘솔 출력·파일 저장·로그서버 전송 세 가지 목적지를 **같은 클래스, 같은 메서드**로 다루고, 목적지별
켜고 끄기·레벨은 `setting.toml`의 `[log]` 카테고리로 정한다.

**목표**
- 동기 호출 API(`log.info(...)` 등). 호출은 즉시 반환하고, 실제 출력(콘솔 쓰기·파일 쓰기·네트워크
  전송)은 백그라운드에서 처리한다.
- 콘솔·파일·로그서버가 같은 레코드를 공유하고, 형식만(JSON 뼈대는 공통, 콘솔만 텍스트 옵션) 다르다.
- 나중에 여러 서버에 배포되어도 로그서버 하나가 받는 로그를 발신처별로 구분할 수 있다.
- `trading_core` 내부뿐 아니라 이 라이브러리를 쓰는 **바깥 앱의 코드**도 같은 모듈로 로그를 찍을 수
  있다. `get_logger(name)`은 이름에 접두를 강제하지 않으므로, 앱은 자기 패키지명으로(`myapp.strategy`
  등) 로거를 만들어도 같은 콘솔·파일·서버 싱크로 흘러간다(3절).

**비목표 (이번 설계에서 다루지 않음)**
- 로그서버 자체의 구현(수신·저장·조회). 이 문서는 클라이언트 쪽 `ServerSink`의 확장 지점만 정의한다.
- 기존 `helper.py`/`domain.py`의 `print` 호출을 이 로그 모듈로 교체하는 작업(별도 과제).
- 메트릭·트레이싱 등 로그 이외의 관측성(observability) 기능.

## 2. 공개 API (`src/trading_core/logger.py`)

```python
def configure(path: str | Path | None = None) -> None: ...
def get_logger(name: str) -> TrLogger: ...
def shutdown() -> None: ...
```

- **`configure(path=None)`** — 설정을 읽어 큐·리스너·싱크(콘솔/파일/서버)를 구성한다. 이미 구성된
  상태에서 다시 부르면 기존 `QueueListener`를 멈추고 새로 구성한다(설정 리로드).
  탐색 순서는 다음과 같고, 앞선 항목이 있으면 뒤는 보지 않는다:
  1. 인자로 받은 `path`
  2. 환경변수 `TRADING_CORE_SETTINGS`
  3. 현재 작업 디렉터리(`Path.cwd()`)의 `setting.toml`
  4. 위 셋 다 없으면 **기본값**으로 동작(콘솔에 텍스트 형식만 켠 상태). 파일이 지정됐는데 없으면
     `LogConfigError`.
- **`get_logger(name)`** — `logging.getLogger(name)`을 그대로 감싼 `TrLogger`를 돌려준다. `trading_core.`
  같은 접두를 강제로 붙이지 않는다 — 호출부가 stdlib 관례대로 `get_logger(__name__)`을 쓰면
  `trading_core` 내부 모듈은 자연히 `"trading_core.domain"`이 되고, 이 라이브러리를 가져다 쓰는
  바깥 앱은 `"myapp.strategy"`처럼 **자기 패키지명**으로 로거를 만들 수 있다(3절 참고).
  로거를 얻는 것만으로는 설정을 읽지 않는다. `configure()`가 아직 불리지 않았으면 **처음 로그를 남길
  때** 기본 탐색으로 `configure()`를 자동 실행한다(라이브러리 코드가 `configure()`를 직접 부르지 않아도
  동작하게 하기 위함). 모듈 맨 위의 `log = get_logger(__name__)`가 import 시점에 파일을 읽지 않고,
  앱이 첫 로그 전에 `configure(path)`를 부르면 그 설정이 그대로 쓰인다.
- **`shutdown()`** — 큐에 남은 레코드를 모두 내보낸 뒤 싱크를 닫고, 루트 로거의 핸들러·레벨과
  `[log.levels]`로 바꾼 레벨을 원래대로 돌린다. `atexit.register(shutdown)`으로 프로세스 종료 시 자동
  호출되도록 등록한다. `shutdown()` 뒤의 로그 호출은 **자동 구성을 하지 않는다**(종료 중에 남은 로그가
  리스너 스레드를 다시 띄우지 않도록). 다시 쓰려면 `configure()`를 명시적으로 부른다.

**호출 형태 — 얇은 래퍼 `TrLogger`**

`logging.Logger`를 그대로 노출하지 않고, 키워드 인자를 구조화 필드로 모으는 얇은 래퍼를 둔다:

```python
log = get_logger(__name__)   # trading_core 내부: "trading_core.domain" / 바깥 앱: "myapp.strategy"
log.info("구독 갱신", symbol="BTC", union_size=3)
log.error("바인더 콜백 실패", exc_info=True, req_id=req.get_model_inst_id())
```

`TrLogger.debug/info/warning/error/critical(msg, /, *, exc_info=False, **fields)`는 내부적으로
`logging.Logger.log(level, msg, extra={"tr_fields": fields}, stacklevel=3)`을 호출한다. `fields`는 JSON
레코드의 `fields` 객체가 된다. `msg`는 위치 전용이라 `msg=...`도 필드 이름으로 쓸 수 있다.
`exc_info=True`면 현재 예외 정보를 잡아 `exc` 필드로 직렬화하고, `exception(msg, **fields)`는
`error(..., exc_info=True)`의 줄임이다. `stacklevel=3`이라 `module`/`func`/`line`은 래퍼가 아니라
호출부를 가리킨다.

콘솔·파일·서버 모두 이 호출 **하나**로 도달한다. 목적지별 on/off·레벨은 오직 `setting.toml`이 정한다.

## 3. 내부 구조

```
호출 스레드/태스크 ── TrLogger.info(...) ── logging.Logger ── QueueHandler
                                                                   │  (prepare()에서 asyncio 태스크명,
                                                                   │   exc_info를 레코드에 미리 심음)
                                                              SimpleQueue
                                                                   │
                                                     QueueListener (전용 스레드 하나)
                                                     ├── ConsoleSink  (StreamHandler, json | text)
                                                     ├── FileSink     (TimedRotatingFileHandler, .jsonl)
                                                     └── ServerSink   (자리만: 배치 버퍼 + send_batch 훅)
```

- 표준 라이브러리 `logging.handlers.QueueHandler` + `QueueListener` 조합을 그대로 쓴다. 호출 스레드는
  큐에 넣기만 하고 반환하므로 이벤트 루프를 막지 않으며, 루프가 멈춰 있어도(예: 동기 코드 블로킹)
  이미 큐에 들어간 레코드는 리스너 스레드가 계속 내보낸다.
- `asyncio.current_task()`의 이름은 리스너 스레드(다른 컨텍스트)에서 읽을 수 없으므로, **호출 쪽**
  `QueueHandler.prepare()`를 오버라이드해 레코드 생성 시점에 태스크 이름을 심는다. 태스크가 없으면
  `None`.
- 큐는 `queue.SimpleQueue`(무제한). 크기 제한과 백프레셔는 다루지 않는다 — 위험은 "8. 수명 주기와
  실패 정책"에 명시.
- **`QueueHandler`는 실제 Python 루트 로거(`logging.getLogger()`, 이름 `""`)에 붙인다.** `trading_core.*`와
  `myapp.*`는 서로 다른 트리라 공통 조상이 루트뿐이므로, 라이브러리 내부 로그와 바깥 앱 로그를 같은
  싱크로 모으려면 이 지점밖에 없다. 개별 로거(`trading_core.domain` 등)는 `propagate`를 건드리지
  않는다(기본값 `True`) — 그래야 위로 올라가 루트의 핸들러에 닿는다.
- 싱크별로 독립된 레벨 필터를 둔다. 루트 로거 자체의 레벨은 `[log].level`이며, 이보다 낮은 레벨은
  큐에 들어가기 전에 걸러진다. 특정 하위 로거(예: 시끄러운 서드파티 라이브러리)만 따로 낮추거나
  올리고 싶으면 `[log.levels]`로 이름별 레벨을 덮어쓴다(6절).
- **알아 둘 제약**: 이 모듈이 루트 로거의 핸들러를 소유한다고 가정한다. 애플리케이션이 별도로
  `logging.basicConfig()`나 자체 루트 핸들러를 구성하면 핸들러가 중복되거나 레코드가 두 번 나갈 수
  있다. 앱이 로깅을 직접 설정하려면 이 모듈을 쓰지 않거나, 이 모듈의 `configure()`만 쓰고 자체
  루트 설정은 하지 않아야 한다.

## 4. JSON 레코드 스키마

```json
{
  "ts": "2026-09-22T04:12:33.501Z",
  "level": "INFO",
  "logger": "trading_core.domain",
  "msg": "구독 갱신",
  "module": "domain",
  "func": "update",
  "line": 214,
  "process": 48213,
  "thread": "MainThread",
  "task": "task-domain-update-BTC",
  "service": "trader-kr-01",
  "host": "ip-10-0-1-23",
  "pid": 48213,
  "instance_id": "trader-kr-01@ip-10-0-1-23:48213",
  "fields": { "symbol": "BTC", "union_size": 3 },
  "exc": null
}
```

| 필드 | 설명 |
| --- | --- |
| `ts` | UTC, ISO 8601, 밀리초까지 |
| `level` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `logger` | `get_logger(name)`에 넘긴 이름 그대로(관례상 `__name__`). 라이브러리 내부는 `trading_core.<모듈>`, 바깥 앱은 앱 자신의 패키지명 |
| `msg` | 사람이 읽는 메시지 |
| `module`/`func`/`line` | 호출 위치 (`logging`이 기본 제공) |
| `process`/`thread` | 표준 `logging` 제공 값 |
| `task` | asyncio 태스크 이름, 없으면 `null` |
| `service`/`host`/`pid`/`instance_id` | 발신처 식별 (아래 5절) |
| `fields` | 호출 시 넘긴 키워드 인자를 모은 dict |
| `exc` | `exc_info=True`일 때 `{"type", "message", "traceback"}`, 아니면 `null` |

- `service`/`host`/`pid`/`instance_id` 네 필드는 **`configure()` 시점에 한 번만 계산**해 프로세스가
  내보내는 모든 레코드에 고정 주입한다(레코드마다 재계산하지 않음).
- JSON으로 직렬화할 수 없는 `fields` 값은 `repr()` 문자열로 대체한다. `TrBaseModel` 인스턴스는
  `model_dump(mode="json")`을 우선 시도한다.
- **콘솔 text 형식** 예시(사람이 읽기 위한 것이고, 파일·서버는 항상 JSON):
  ```
  2026-09-22T04:12:33.501Z INFO  [trader-kr-01@ip-10-0-1-23:48213] trading_core.domain: 구독 갱신 {symbol=BTC, union_size=3}
  ```
  `[service@host:pid]` 접두를 넣어, 여러 서버의 콘솔 로그를 한 곳(예: 로그 집계 뷰어)에서 섞어 봐도
  어디서 온 줄인지 바로 구분되게 한다.

## 5. 다중 서버 배포와 발신처 식별

지금은 로컬 단일 프로세스로만 돈다. 이후 같은 코드가 여러 서버에 배포되고, 그 로그를 받는
로그서버는 **하나**다. 로그서버(및 파일·콘솔에도 동일하게) 쪽에서 "어느 서버, 어느 프로세스가
보낸 로그인지" 구분할 수 있어야 하므로 다음 네 값을 모든 레코드에 싣는다.

- **`service`** — `setting.toml`의 `[log] service_name`에 사람이 직접 지정(예: `"trader-kr-01"`).
  운영자가 서버 역할을 이름으로 붙일 수 있게 하기 위함. 생략하면 `socket.gethostname()`으로 대체.
- **`host`** — 항상 `socket.gethostname()`. `service_name`을 안 붙인 배포에서도 최소한의 구분이
  되도록 별도 필드로 남긴다.
- **`pid`** — 항상 `os.getpid()`. 같은 서버에 워커 프로세스가 여러 개 떠도(예: 멀티프로세스 실행기)
  구분되게 한다.
- **`instance_id`** — `f"{service}@{host}:{pid}"` 조합 문자열. 로그서버 쪽에서 필터·그룹핑 키로
  바로 쓰기 편하도록 미리 만들어 둔다.

## 6. `setting.toml` `[log]` 스키마

`trading-core`는 라이브러리이므로 `setting.toml`은 이를 사용하는 애플리케이션 쪽에 있을 수 있다.
`[log]`를 포함한 다른 카테고리(예: `[exchange]`)는 이 모듈이 관여하지 않고 무시한다. `tomllib`로
읽고 `pydantic`(`extra="forbid"`) 모델로 검증한다.

모든 키에 설명을 단 예시는 저장소 루트의 `setting.example.toml`에 있다(값은 모두 기본값). `setting.toml`로
복사해 쓴다. 이름이 달라 CWD 탐색에는 걸리지 않는다.

```toml
[log]
level = "INFO"
service_name = "trader-kr-01"   # 생략 시 socket.gethostname()으로 대체

[log.levels]                    # 선택. 특정 로거 이름만 레벨을 덮어쓴다(기본값: 비어 있음)
# "asyncio" = "WARNING"
# "urllib3" = "WARNING"

[log.console]
enabled = true
level = "DEBUG"
format = "text"        # "json" | "text"
stream = "stderr"      # "stdout" | "stderr"

[log.file]
enabled = false
level = "INFO"
path = "logs/trading_core.jsonl"
when = "midnight"       # TimedRotatingFileHandler의 회전 시점
backup_count = 14       # 보관할 로테이션 파일 개수
utc = true

[log.server]            # 아직 미구현 — enabled=true면 configure()가 즉시 실패한다
enabled = false
level = "WARNING"
url = ""
batch_size = 100
flush_interval = 1.0    # 초
timeout = 3.0           # 초
max_buffer = 10000      # 초과분은 오래된 것부터 버리고, 버려진 개수를 센다
```

| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `log.level` | `"INFO"` | (진짜) 루트 로거 레벨 — `trading_core`뿐 아니라 이 프로세스의 모든 로거에 적용 |
| `log.service_name` | `socket.gethostname()` | 이 프로세스를 가리키는 사람이 읽는 이름 |
| `log.levels."<이름>"` | (없음) | 특정 로거 이름(예: `"asyncio"`, `"myapp.noisy"`)만 레벨을 개별 덮어씀. 기본은 빈 테이블 |
| `log.console.enabled` | `true` | 콘솔 싱크 on/off |
| `log.console.level` | `"DEBUG"` | 콘솔 싱크 레벨 |
| `log.console.format` | `"text"` | `"text"`(사람용) 또는 `"json"` |
| `log.console.stream` | `"stderr"` | `"stdout"` 또는 `"stderr"` |
| `log.file.enabled` | `false` | 파일 싱크 on/off |
| `log.file.level` | `"INFO"` | 파일 싱크 레벨 |
| `log.file.path` | `"logs/trading_core.jsonl"` | 로그 파일 경로(상대 경로는 CWD 기준) |
| `log.file.when` | `"midnight"` | `TimedRotatingFileHandler`의 `when` 인자 |
| `log.file.backup_count` | `14` | 보관할 로테이션 파일 수 |
| `log.file.utc` | `true` | 로테이션 기준 시각을 UTC로 쓸지 |
| `log.server.enabled` | `false` | 서버 싱크 on/off (`true`면 미구현으로 실패) |
| `log.server.level` | `"WARNING"` | 서버 싱크 레벨 |
| `log.server.url` | `""` | 로그서버 엔드포인트 (미구현) |
| `log.server.batch_size` | `100` | 한 번에 보낼 레코드 수 (미구현) |
| `log.server.flush_interval` | `1.0` | 배치가 안 차도 강제로 보내는 주기(초) (미구현) |
| `log.server.timeout` | `3.0` | 전송 타임아웃(초) (미구현) |
| `log.server.max_buffer` | `10000` | 전송 실패 시 쌓일 수 있는 최대 레코드 수 (미구현) |

`setting.toml` 파일이 없거나 `[log]` 섹션이 없으면 기본값(콘솔 text만 켠 상태)으로 동작한다.
스키마에 없는 키가 있으면 `LogConfigError`(검증 실패로 즉시 알아차리도록 `extra="forbid"`).

## 7. 로그서버 확장 지점 (미구현)

`ServerSink`는 이번 단계에서 클래스 뼈대와 계약만 정의하고 실제 전송은 구현하지 않는다.
`configure()`는 아직 이 싱크를 만들지 않는다.

지금 있는 것:

- 계약: `send_batch(lines: list[str]) -> None` — JSON 문자열(레코드 하나당 한 줄) 배치를 받아 전송한다.
  지금은 `NotImplementedError`다. 전송을 구현할 때 이 메서드를 채운다.
- 배치 버퍼: 줄이 `batch_size`개 모이면 `flush()`가 `batch_size`씩 보낸다. `send_batch()`가 예외를
  던지면 보내지 못한 줄은 버퍼에 남고 다음 `flush()`(또는 `close()`)에서 다시 보낸다.
- 버퍼가 `max_buffer`를 넘으면 **오래된 줄부터 버리고** `dropped`에 센다.

전송을 구현할 때 정할 것:

- `flush_interval`마다 배치가 안 차도 보내는 타이머, `timeout`, 재시도 횟수·백오프.
- 지금은 실패한 전송을 다음 레코드마다 다시 시도한다. 백오프 없이 두면 로그서버가 죽었을 때 레코드마다
  전송을 시도하게 된다.
- 버린 개수(`dropped`)를 경고 로그로 남기는 시점(다음 성공 전송 때 콘솔/파일 싱크로).
- `[log.server].enabled = true`인데 실제 전송 구현이 없는 지금 상태에서는, `configure()`가
  `LogConfigError("로그서버 전송은 아직 구현되지 않았다")`로 **즉시 실패**한다(fail-fast). 이렇게 해야
  "설정은 켰는데 조용히 안 나가는" 상태를 피할 수 있다.

## 8. 수명 주기와 실패 정책

- `shutdown()`과 `atexit` 훅은 `QueueListener.stop()`을 호출해 큐에 남은 레코드를 모두 처리한 뒤
  스레드를 정리한다.
- `configure()`를 재호출(설정 리로드)하면 기존 리스너를 먼저 멈추고 새 싱크로 교체한다. 교체 사이의
  아주 짧은 창에서는 레코드가 큐에 쌓이고, 새 리스너가 시작되면 그대로 처리된다(유실 없음).
- 싱크 하나(예: 파일 쓰기 실패, 콘솔 스트림 닫힘)의 예외가 다른 싱크를 막으면 안 된다. 각 `Handler`의
  `handleError()`를 오버라이드해 실패를 표준 에러로 한 번 경고하고 그 레코드만 버린 뒤 계속 진행한다.
- 큐가 무제한(`SimpleQueue`)이므로, 소비(리스너)가 생산(로그 호출)을 못 따라가면 메모리가 계속
  늘어날 수 있다. 지금 단계에서는 이 위험을 문서화만 하고 크기 제한/백프레셔는 다루지 않는다
  (필요해지면 별도 TODO로 분리).

## 9. 예외

`exceptions.py`에 `LogConfigError`를 추가한다(설정 파일 파싱 실패, 스키마 위반, 미구현 싱크를 켠
경우 등에 사용).

## 10. 테스트 계획 (구현 시 `tests/test_logger.py`)

- 설정 탐색 순서: `path` 인자 > 환경변수 > CWD `setting.toml` > 기본값 (각각 `tmp_path` +
  `monkeypatch`로 격리)
- 스키마 위반(`extra` 키, 잘못된 `format`/`stream` 값) 시 `LogConfigError`
- `get_logger(name)`이 `name`을 그대로 로거 이름으로 쓰는지(접두 강제 없음): `trading_core.foo`와
  `myapp.bar`처럼 서로 다른 트리의 이름으로 만든 로거가 **같은** 싱크로 도달하는지
- `[log.levels]`로 지정한 이름만 레벨이 덮어써지는지, 지정 없는 로거는 `[log].level`을 따르는지
- JSON 레코드 필드 검증: `service`/`host`/`pid`/`instance_id` 값, `fields` 병합, `exc` 직렬화
- asyncio 태스크명 캡처: 태스크 안/밖에서 호출했을 때 `task` 필드
- 싱크별 레벨 필터: 콘솔은 통과, 파일은 걸러지는 경우 등
- `shutdown()`이 큐에 남은 레코드를 모두 내보낸 뒤 리스너 스레드를 정리하는지(flush 보장)
- 파일 로테이션: `tmp_path`에 `TimedRotatingFileHandler` 구성 후 회전 파일이 생기는지(시간을
  얼마나 흉내 낼지는 구현 시 결정)
- `[log.server].enabled = true`면 `configure()`가 `LogConfigError`로 즉시 실패하는지

## 11. 미결 사항

- 로그서버 프로토콜(HTTP? WebSocket? UDP?) — `ServerSink`가 실제로 구현될 때 정한다.
- 기존 `helper.py`/`domain.py`의 `print` 호출을 이 모듈로 교체할지, 한다면 시점은 언제인지.
- 민감 정보(요청 필드 등)를 로그에 남길 때 마스킹이 필요한지 — 지금은 다루지 않는다.
