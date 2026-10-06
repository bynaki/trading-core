# Plan

> 형식: `### [done] <prefix>:<word>` 제목 아래 할 일을 적는다. `<prefix>:<word>`가 항목 구분자이자
> 관련 항목을 묶는 태그다 — 같은 `prefix`를 쓰는 항목은 같은 주제로 읽는다. 완료된 항목 중 아직
> 열린 항목과 관련이 없어진 것은 `docs/done.md`로 옮기고 여기서 지운다(상세 규칙은 `AGENTS.md`
> "새 세션을 시작할 때" 참고).

> 열린 과제는 logger:server-transport, api:typed-subscription이다.

### [done] logger:core
프로젝트 전반 로그 모듈(`logger.py`). 설계는 `docs/log.spec.md`에 있다. `setting.toml`의 `[log]`
카테고리로 콘솔·파일·로그서버 스위치를 설정하고, 레코드마다 `service`/`host`/`pid`/`instance_id`로
발신처를 구분한다. 큐 핸들러는 진짜 루트 로거에 붙어 `trading_core.*`와 바깥 앱의 로거를 같은
싱크로 모은다. 구현하며 정한 것: 자동 구성은 `get_logger()`가 아니라 **첫 로그 호출** 때 한다(import
시점에 파일을 읽지 않게). `shutdown()` 뒤에는 자동 구성하지 않는다. 큐와 큐 핸들러는 재구성해도
유지해, 리스너를 갈아 끼우는 사이에 다른 스레드가 남긴 레코드가 빠지지 않는다.
재현·검증: tests/test_logger.py. 재구성 중 유실은 경합이라 `test_reconfigure_loses_nothing_logged_concurrently`가
확률적으로 잡는다(큐를 재구성마다 새로 만드는 변형을 약 2/3 확률로 잡음).
남은 것은 아래 logger:server-transport로 남겨 두었다. 관련 항목이 아직 열려 있어
`docs/done.md`로 옮기지 않았다.

### logger:server-transport
로그서버로 실제 전송하기. `ServerSink.send_batch()`가 `NotImplementedError`다. 배치 버퍼·`dropped`
카운트까지는 있고(`docs/log.spec.md` 7절), 프로토콜(HTTP? WebSocket? UDP?)과 `flush_interval`
타이머·재시도·백오프는 실제로 붙일 로그서버가 정해지면 같이 정한다. `[log.server] enabled = true`인
채로 이 항목을 그대로 두면 `configure()`가 `LogConfigError`로 fail-fast하므로, 정책 미정 상태에서도
"조용히 안 나가는" 사고는 나지 않는다.

### [done] api:export-model-validation-error
`ModelValidationError`(`cast_model()`·`load_model()`·`parse_dump()`가 던진다)를 최상위 `trading_core`에서
내보낸다. ex28·`tests/test_model.py`가 최상위에서 import한다. `ModelError`의 하위 클래스로 묶지 않았다 —
`ModelError`는 코드를 잘못 쓴 것, `ModelValidationError`는 받은 입력이 맞지 않는 것이라
`except ModelError`가 깨진 입력까지 삼키면 안 된다. `TaskManagerError`(`TaskManager`가 비공개)와
`LogConfigError`(로그 API가 `trading_core.logger` 하위 모듈)는 내보내지 않는다.

### api:typed-subscription
`Domain.subscribe()`가 돌려주는 `Subscription`의 `request`가 `BaseRequest`로만 타입이 잡힌다
(`Subscription[T]`는 제네릭인데 `subscribe()`가 요청 타입을 이어 주지 않는다). ex27은
`cast_model(sub.request, TickReq)`로 좁힌다. `subscribe()`·`stream()`을 요청 타입에 제네릭으로 할지 본다.
