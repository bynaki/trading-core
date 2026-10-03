# Plan

> 형식: `### [done] <prefix>:<word>` 제목 아래 할 일을 적는다. `<prefix>:<word>`가 항목 구분자이자
> 관련 항목을 묶는 태그다 — 같은 `prefix`를 쓰는 항목은 같은 주제로 읽는다. 완료된 항목 중 아직
> 열린 항목과 관련이 없어진 것은 `docs/done.md`로 옮기고 여기서 지운다(상세 규칙은 `AGENTS.md`
> "새 세션을 시작할 때" 참고).

> 열린 과제는 logger:server-transport, policy:symbol-failure(보류)다.

### [done] policy:callback-exception
사용자 콜백·generator·Sender가 던질 때의 정책을 정하고 구현했다. 전에는 원천·파생 generator가 던지면
`_pump` 태스크만 조용히 죽어(DEBUG 로그) 스테이지가 `active_symbols`를 든 채 남았고, 합집합이 같으면
재시작도 안 돼 소비자와 하위 파생·세션이 영영 굶었다. Sender 하나가 던지면 `SymbolRouter`의 `TaskGroup`을
거쳐 공유 generator가 죽었고, 세션 `invoke()`가 던지면 슬롯 채널이 안 닫혀 상위가 계속 쌓였다.
`unbind_cb`·`detach_cb`가 던지면 `detach()`가 중간에 끊기고 형제 콜백까지 취소됐다.

정한 정책(`AGENTS.md` 핵심 불변식 7·8):
- **코어는 재시도하지 않는다**(원천 포함). 재시도를 단계마다 두면 요청이 여러 단계를 거칠 때 곱해진다.
  버틸지(재연결 등)는 binder가 generator 안에서 정한다.
- **실패 단위는 (content_id, 심볼 부분집합)**. 스테이지·슬롯을 내리고 영향받은 소비자에게 자기 심볼만
  담은 `StageFailed`(직렬화할 수 있게 `cause`는 문자열)를 `subscribe(..., on_error=)`로 알린다. 원천
  실패는 하위 파생·세션 슬롯으로 연쇄한다. 세션은 슬롯(하위 표기 심볼) 단위, `always` 슬롯 실패만 세션
  전체. 실패한 심볼은 구독에서 빠지고 `update()`로 다시 넣으면 새 스테이지가 init부터 선다.
- **Sender 하나의 실패는 격리**: 그 Sender만 떼고 공유 generator는 계속.
- **정리 실패는 삼킨다**: 끝까지 정리하고 ERROR 로그. 호출자에게 올리지 않는다(`ExceptionGroup`으로
  올리는 안도 검토했으나, 정리는 구독을 연 쪽이 아니라 스테이지 쪽 일이라 호출자가 다룰 수 없다).
- `stream()`은 실패하면 `StageFailed`를 던지고 끝난다.
- 곁들여 고친 것: `open_slot()`이 bind 콜백을 다 받은 뒤에만 슬롯을 등록(도중 실패 시 부분 상태 없음),
  빈 집합 `update()`가 스테이지를 새로 만들지 않음, 빠진 스테이지로 락을 기다리던 `update()`는 지금
  등록된 스테이지로 넘김, generator 수명을 `pump()`의 `aclosing` 안으로 옮김, 원천·파생 스테이지 생성을
  `_get_or_create_shared_stage()` 하나로 합침, `TaskManager` 예외 훅을 ERROR로.
재현·검증: tests/test_domain.py의 "실패 정책" 절, tests/test_routing.py의
`test_symbol_router_isolates_a_failing_sender`. 수정을 하나씩 되돌리면 해당 테스트만 깨지는 것을 확인했다.
남은 것은 아래 policy:symbol-failure, policy:init-failure로 남겨 두었다.
예제: ex10이 원천 generator·Sender·detach 콜백이 던질 때와 `stream()`의 실패를 판정과 함께 보여 준다
(세션 슬롯·init 실패는 테스트만 덮는다).

### policy:symbol-failure
원천이 **심볼 하나만** 실패로 알리는 길이 없다(보류). 원천 generator는 심볼 합집합 하나로 돌므로, 한
소비자가 넣은 잘못된 심볼(상장 폐지 등) 때문에 binder가 던지면 같은 원천을 쓰는 모든 소비자가 실패한다.
지금은 binder가 그런 심볼을 던지지 말고 건너뛰도록 해야 한다. 필요해지면 binder가 "`X`는 못 준다"를
알리고 코어가 스테이지를 죽이지 않은 채 `StageFailed(symbols={X})`만 내보내는 API를 둔다.

### [done] policy:init-failure
`init_cb`가 던질 때도 다른 실패처럼 `StageFailed`로 알린다(`AGENTS.md` 핵심 불변식 7). 전에는 원래
예외가 `update()`(세션은 `subscribe()`) 호출자에게 올라갔는데, 경로에 따라 상태가 어긋났다:
파생의 상위 init이 던지면 파생 스테이지가 소비자 심볼을 든 채 generator 없이 남았고(예외를 받은
소비자가 실은 구독된 상태), 세션 슬롯의 상위 init이 던지면 `sync_upstreams()`의 `TaskGroup`을 거쳐
`ExceptionGroup`이 올라가 어느 심볼인지 알 수 없었고 형제 상위의 `update()`가 도중에 취소될 수 있었으며
실패한 심볼의 슬롯은 bind된 채 열려 있었다.

정한 것:
- 공유 스테이지(원천·파생)를 만들다 init이 던지면 스테이지를 두지 않고 그 센더의 `on_fail`로 요청 심볼의
  실패를 알린다(`_update_shared_stage()`, 이름은 `_ensure_upstream_stage()`에서 바꿨다). 그래서 상위
  init 실패는 상위 스테이지 실패와 같은 연쇄 경로를 탄다. 파생은 상위를 못 세우면 generator를 띄우지 않는다.
- 세션 init은 공유 스테이지처럼 첫 `update()`로 미뤘다. 던지면 요청 심볼의 실패를 `update()`가 돌아오기
  전에 알리고, 다음 `update()`가 다시 init한다.
- binder 누락 같은 등록 오류(`DomainError`)는 init 실패가 아니므로 지금처럼 호출자에게 간다
  (`_InitFailed`로 init 예외만 가른다).
재현·검증: tests/test_domain.py의 `*init*` 테스트 5개. 수정 전 `domain.py`로 돌리면 5개 모두 깨진다.
예제: ex11이 원천·파생 상위·세션 자신·세션 슬롯 상위의 init 실패와 등록 오류(`DomainError`)를 판정과
함께 보여 준다. 수정 전 `domain.py`로 돌리면 1~4번이 회귀로 나온다.
파생이 상위를 못 세웠을 때 generator를 띄우지 않는 가드는 테스트로 고정하지 못했다 — 실패 처리 태스크가
generator의 첫 걸음보다 먼저 락을 잡아, 가드를 빼도 순서상 generator 본문이 돌지 않는다.

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
