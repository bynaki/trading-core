# ex09: 로그 모듈(`trading_core.logger`) 쓰기

binder와 소비자 코드에서 `trading_core.logger`로 로그를 남기고, 같은 레코드가 설정에 따라
콘솔(text)과 파일(JSON)로 **다르게 걸러져** 나가는 것을 보인다. 마지막에 파일을 발신처
(`instance_id`)로 걸러 읽어, 여러 서버의 로그가 모인 곳에서 한 프로세스의 로그만 고르는 법도
보인다.

설계는 `docs/design.log.md`, 모든 설정 키의 설명은 저장소 루트의 `setting.example.toml`에 있다.

## 파일 구성

- `setting.toml`: 이 예제 전용 설정. 콘솔은 INFO 이상 text, 파일은 DEBUG까지 JSON,
  시끄러운 로거 `ex09.wire`는 `[log.levels]`로 INFO에 묶는다.
- `ex09.py`: 원천 `PriceFeedReq`. init·generate·`finally`·detach 곳곳에서 로그를 남긴다.
  네 번째 틱은 깨진 페이로드라 잡은 예외를 `log.exception()`으로 남긴다.
- `run_ex.py`: `configure(setting.toml)` → 피드 구독 → `configure(examples/setting.toml)`로
  예제 공용 설정에 되돌림 → 파일 요약.

## 쓰는 법 세 줄

```python
from trading_core.logger import configure, get_logger, shutdown

log = get_logger(__name__)            # 모듈 맨 위. 이것만으로는 설정 파일을 읽지 않는다
log.info("수신", symbol="BTC", price=101.0)   # 키워드 인자는 레코드의 fields가 된다
```

- `configure(path)`는 선택이다. 부르지 않으면 **첫 로그 때** 환경변수 `TRADING_CORE_SETTINGS`,
  그다음 현재 디렉터리의 `setting.toml`을 찾고, 없으면 기본값(콘솔 text만)으로 동작한다.
- 호출은 큐에 넣고 곧바로 반환한다. 실제 출력은 전용 스레드가 하므로 이벤트 루프를 막지 않는다.
- `shutdown()`은 큐를 비우고 싱크를 닫는다. 프로세스가 끝날 때 자동으로 불리므로 보통은 부를
  필요가 없다. `configure()`를 다시 불러 재구성해도 이전 리스너가 큐를 비우고 싱크를 닫는다.
  이 예제는 곧바로 파일을 읽어야 해서 공용 설정으로 **재구성**한다. `shutdown()`을 쓰지 않는
  이유는 [알아둘 점](#알아둘-점)에 있다.

## 실행

```bash
uv run examples/main.py ex09
```

콘솔은 이렇다(`<host>`·`<pid>`는 실행 환경마다 다르다). 이 예제 전용 설정은 콘솔을 `"text"`
형식으로 두어 시각과 `[ex09-local@…]` 발신처를 보인다. 앞뒤의 짧은 줄은 예제 공용 설정
(`"text.simple"`)으로 찍힌 것이라, 형식이 바뀌는 곳이 곧 설정이 바뀐 곳이다:

```text
INFO  examples: 예제 실행 (serial): ex09

…Z INFO  [ex09-local@<host>:<pid>] ex09.run_ex: ━━━━━━━━━━ 시작: 로그 모듈 쓰기 ━━━━━━━━━━ {take=6}
…Z INFO  [ex09-local@<host>:<pid>] ex09.ex09: 피드 연결
  {
    "base": 100.0,
    "content_id": "ex09.ex09@PriceFeedReq:…"
  }
…Z INFO  [ex09-local@<host>:<pid>] ex09.ex09: 구독 시작 {symbols=['BTC', 'ETH']}
…Z INFO  [ex09-local@<host>:<pid>] ex09.run_ex: 수신 {symbol=BTC, price=101.0}
…Z INFO  [ex09-local@<host>:<pid>] ex09.run_ex: 수신 {symbol=ETH, price=103.0}
…Z INFO  [ex09-local@<host>:<pid>] ex09.run_ex: 수신 {symbol=BTC, price=103.0}
…Z ERROR [ex09-local@<host>:<pid>] ex09.ex09: 페이로드 파싱 실패, 이 틱은 건너뛴다 {symbol=ETH, raw=ETH=??}
Traceback (most recent call last):
  …
ValueError: could not convert string to float: '??'
…Z WARNING [ex09-local@<host>:<pid>] ex09.ex09: 가격 급변 감지 {symbol=BTC, price=105.0}
…Z INFO  [ex09-local@<host>:<pid>] ex09.run_ex: 수신 {symbol=BTC, price=105.0}
…Z INFO  [ex09-local@<host>:<pid>] ex09.run_ex: 수신 {symbol=ETH, price=107.0}
…Z INFO  [ex09-local@<host>:<pid>] ex09.run_ex: 수신 {symbol=BTC, price=107.0}
…Z INFO  [ex09-local@<host>:<pid>] ex09.ex09: 구독 정리 {symbols=['BTC', 'ETH'], ticks=7}
…Z INFO  [ex09-local@<host>:<pid>] ex09.ex09: 피드 종료 {ticks=7}
…Z INFO  [ex09-local@<host>:<pid>] ex09.run_ex: 구독 끝 {received=6}
INFO  ex09.run_ex: ----- logs/ex09.jsonl 에서 instance_id=ex09-local@<host>:<pid> 인 레코드 22건 -----
INFO  ex09.run_ex: 레벨별 {INFO=12, DEBUG=8, ERROR=1, WARNING=1}
INFO  ex09.run_ex: 로거별 {ex09.run_ex=8, ex09.ex09=12, trading_core.helper=2}
INFO  ex09.run_ex: 태스크별 {Task-1=12, PriceFeedReq@ex09.ex09:…:2=10}
```

그 뒤에 예외를 담은 레코드 하나를 JSON으로 펼쳐 보인다. 파일은 저장소 루트의
`logs/ex09.jsonl`에 쌓인다(실행한 디렉터리 기준 상대 경로, `.gitignore` 대상).

## 관전 포인트

**콘솔에 없는 DEBUG 8건이 파일에는 있다.** `log.debug("틱 발행", ...)` 6건은 콘솔(INFO)에서는
걸러지고 파일(DEBUG)로만 간다. 나머지 2건은 `trading_core.helper`(`TaskManager`)의 태스크 제출·취소
로그다 — 라이브러리 내부 로그도 같은 설정을 따른다. 호출은 하나, 목적지별 on/off와 레벨은 설정만 정한다.
레코드는 루트 레벨(`[log].level`)과 싱크 레벨을 **둘 다** 넘어야 그 싱크로 나간다.

**`ex09.wire`는 어디에도 없다.** 틱마다 `wire.debug("원시 페이로드", ...)`를 부르지만,
`[log.levels]`에서 이 이름을 INFO로 묶었으므로 파일 싱크가 DEBUG여도 나가지 않는다. 로거별
집계에 `ex09.wire`가 없는 것이 그 결과다. 시끄러운 서드파티 로거(`"asyncio"` 등)를 누를 때
쓰는 방법이다.

**로거 이름에 `trading_core` 접두가 붙지 않는다.** `get_logger(__name__)`이라 이름은 모듈 경로
그대로 `ex09.ex09`·`ex09.run_ex`다(`uv run python examples/ex09/run_ex.py`로 직접 돌리면
`ex09`·`__main__`). 바깥 앱의 로그도 `trading_core` 내부 로그와 같은 싱크로 모인다.

**`task`가 로그가 어느 태스크에서 나왔는지 알려 준다.** generator 본문의 로그(구독 시작·틱
발행·파싱 실패·급변 감지 9건)와 그 태스크의 취소 로그 1건은 `TaskManager`가 스테이지 id로 이름
붙인 태스크(`PriceFeedReq@…:2`)에서 나왔다. 나머지 12건은 메인 태스크(`Task-1`)다 — 소비자 쪽
로그 8건과 태스크 제출 로그에 더해, init 콜백(`피드 연결`)은 `domain.request()`를 부른 쪽에서,
`finally`(`구독 정리`)와 detach(`피드 종료`)는 구독을 끊은 쪽에서 돌기 때문이다. 같은 binder 코드라도 어느 지점이 어느
태스크에서 도는지가 이 필드로 드러난다.

**트레이스백은 메시지가 아니라 `exc`로 간다.** 콘솔 text에서는 메시지 아래에 붙어 보이지만,
JSON 레코드에서는 `msg`는 그대로 두고 `exc: {type, message, traceback}`로 따로 담긴다.
로그서버에서 예외 종류로 거르기 쉽게 하기 위해서다.

**발신처로 거른다.** 모든 레코드에 `service`/`host`/`pid`/`instance_id`가 실린다. 파일은 실행마다
이어 쓰기 때문에 `run_ex.py`는 이번 실행의 `instance_id`로 걸러 읽는다. 여러 서버가 로그서버
하나로 보낼 때 한 프로세스의 로그만 고르는 것도 같은 키로 한다. 서버마다 `service_name`을
다르게 붙이면 된다.

## 알아둘 점

- 로그 모듈은 **프로세스 전역인 루트 로거**에 붙는다. 다른 예제도 모두 같은 로그 모듈로
  출력하므로, ex09가 구성을 바꾸면 그동안은 다른 예제의 줄도 이 설정을 따른다. `parallel`로
  돌리면 다른 예제의 줄도 그동안은 시각과 `[ex09-local@…]`이 붙은 `"text"` 형식으로 찍히고 파일에도 섞여 들어가, 파일 요약의 건수와
  로거별 집계에 `ex01`·`ex05.origin` 같은 이름이 함께 잡힌다. 한 프로세스의 로그가 한 곳으로
  모인다는 것이 그대로 드러나는 셈이다.
- 끝날 때 `shutdown()`이 아니라 공용 설정으로 **재구성**하는 이유가 이것이다. `shutdown()` 뒤의
  로그는 자동으로 다시 구성되지 않으므로, `serial`에서 뒤따르거나 `parallel`에서 함께 도는
  예제의 로그가 어디로도 나가지 않는다. 재구성은 레코드를 잃지 않는다.
- 로그서버 싱크는 아직 뼈대만 있다. `[log.server] enabled = true`로 켜면 `configure()`가
  `LogConfigError`로 실패한다.
- `fields`에 넘긴 값은 그대로 기록된다. 비밀값(키·토큰)을 넘기지 말 것 — 마스킹은 아직 없다.
