# TODO

> 형식: `#### [done] <prefix>:<word>` 제목 아래 할 일을 적는다. `<prefix>:<word>`가 항목 구분자이자
> 관련 항목을 묶는 태그다 — 같은 `prefix`를 쓰는 항목은 같은 주제로 읽는다. 완료된 항목 중 아직
> 열린 항목과 관련이 없어진 것은 `docs/DONE.md`로 옮기고 여기서 지운다(상세 규칙은 `AGENTS.md`
> "새 세션을 시작할 때" 참고).

> 열린 과제는 policy:callback-exception과 logger:server-transport다.

#### policy:callback-exception
TaskManager: task에서 예외가 발생했을 때 TaskManager 단에서 처리할 방법이 없다. 사용자 콜백
(`unbind_cb`·`detach_cb`)이 `TaskGroup` 안에서 던지면 `detach()`가 중간에 끊겨 상위 스테이지가
안 내려가고 `stage.update`/`detach` 교체도 안 된다. generate 콜백의 `finally`도 같은 노출을 갖는다.
정책이 **사용자 결정 대기** 중이므로 임의로 구현하지 말 것.

사용자에게 제시한 선택지:
1. 로그만 남기고 계속 — 정리는 항상 끝나지만 오류를 놓치기 쉽다.
2. **정리를 끝까지 한 뒤 모은 오류를 `ExceptionGroup`으로 재발생** (추천) — 정리 보장 + 호출자도
   오류를 본다. 현재 `TaskGroup` 스타일과 맞는다. 덧붙여 `SendRouter`에서 Sender 하나의 실패를
   격리해 공유 generator가 죽지 않게 한다.
3. 스테이지별 실패 콜백 — 가장 유연하지만 API가 늘어난다.

손댈 자리(`src/trading_core/`):
- `domain.py` `_define_inst_stage()`의 `unbind_symbols()`·`detach()` — 콜백이 던지면 `detach()`가
  중간에 끊긴다.
- `domain.py` 원천 스테이지 `update()`들의 `bind_pack._detach_cb` 호출, generate 콜백의 `finally`.
- `domain.py` `SendRouter.__call__` — `TaskGroup` 안에서 Sender 하나가 던지면 전체가 실패.
- `domain.py` `_task_sequence()` — `seq.invoke()`가 던지면 슬롯 태스크가 조용히 죽는다.
- `helper.py` `TaskManager._task_wrapper()` / `on_task_failure()` — 현재 태스크 예외 처리 지점.

#### [done] logger:core
프로젝트 전반 로그 모듈(`logger.py`). 설계는 `docs/design.log.md`에 있다. `setting.toml`의 `[log]`
카테고리로 콘솔·파일·로그서버 스위치를 설정하고, 레코드마다 `service`/`host`/`pid`/`instance_id`로
발신처를 구분한다. 큐 핸들러는 진짜 루트 로거에 붙어 `trading_core.*`와 바깥 앱의 로거를 같은
싱크로 모은다. 구현하며 정한 것: 자동 구성은 `get_logger()`가 아니라 **첫 로그 호출** 때 한다(import
시점에 파일을 읽지 않게). `shutdown()` 뒤에는 자동 구성하지 않는다. 큐와 큐 핸들러는 재구성해도
유지해, 리스너를 갈아 끼우는 사이에 다른 스레드가 남긴 레코드가 빠지지 않는다.
재현·검증: tests/test_logger.py. 재구성 중 유실은 경합이라 `test_reconfigure_loses_nothing_logged_concurrently`가
확률적으로 잡는다(큐를 재구성마다 새로 만드는 변형을 약 2/3 확률로 잡음).
남은 것은 아래 logger:server-transport로 남겨 두었다. 관련 항목이 아직 열려 있어
`docs/DONE.md`로 옮기지 않았다.

#### logger:server-transport
로그서버로 실제 전송하기. `ServerSink.send_batch()`가 `NotImplementedError`다. 배치 버퍼·`dropped`
카운트까지는 있고(`docs/design.log.md` 7절), 프로토콜(HTTP? WebSocket? UDP?)과 `flush_interval`
타이머·재시도·백오프는 실제로 붙일 로그서버가 정해지면 같이 정한다. `[log.server] enabled = true`인
채로 이 항목을 그대로 두면 `configure()`가 `LogConfigError`로 fail-fast하므로, 정책 미정 상태에서도
"조용히 안 나가는" 사고는 나지 않는다.
