# 인수인계 (2026-09-22)

새 세션은 이 문서부터 읽는다. 프로젝트 전반의 안내는 `AGENTS.md`(`CLAUDE.md`가 참조)에 있고,
과제의 내력은 `docs/TODO.md`에 있다. 이 문서는 **직전 세션이 어디서 멈췄는지**만 다룬다.
일을 이어받아 끝내면 이 문서는 지워도 된다.

## 지금 상태

- 작업 브랜치는 `feat/log`다.
- ruff check · format · pyright(0 errors) · pytest(125 passed) 모두 통과.
  `uv run examples/main.py serial`과 `parallel` 모두 ex01~ex09 완주, 오류 없음.

## 이번 세션에서 한 것 (요약)

TODO 10 — 프로젝트 전반 로그 모듈. 설계부터 구현·예제까지 한 흐름으로 끝냈다. 자세한 내력은
`docs/design.log.md`와 `docs/TODO.md` 10번에 있다.

- **설계**: 처음엔 로그서버 하나가 여러 서버의 로그를 받는 걸 몰랐는데, 사용자가 짚어 줘서
  레코드마다 `service`/`host`/`pid`/`instance_id`를 싣도록 넣었다. 또 `get_logger()`가
  `trading_core.<name>` 접두를 강제하던 초안도 문제였다 — 이 라이브러리를 쓰는 바깥 앱의 로그까지
  라이브러리 네임스페이스에 갇혔다. `logging.getLogger(name)`을 그대로 감싸는 것으로 고쳤고,
  그 결과 큐 핸들러를 `trading_core` 로거가 아니라 **진짜 Python 루트 로거**에 붙여야 했다
  (공통 조상이 거기뿐이라서).
- **구현**: `QueueHandler`/`QueueListener` 위에 동기 호출 + 백그라운드 출력을 쌓았다. 콘솔(text/json)·
  파일(날짜별 회전 JSON Lines)·로그서버(뼈대만, 켜면 `LogConfigError`로 fail-fast) 세 싱크가
  `setting.toml`의 `[log]`로 켜진다. 구현하며 문서에 없던 것도 정했다: 자동 구성은 `get_logger()`가
  아니라 **첫 로그 호출** 때(모듈 import가 파일을 안 읽게), `shutdown()` 뒤엔 자동 구성 안 함,
  큐·큐 핸들러는 재구성해도 유지(리스너 교체 중 다른 스레드의 레코드가 안 빠지게).
- **검증 방법**: 테스트를 쓴 뒤 핵심 동작 8개를 하나씩 코드에서 깨 보고 그 테스트만 실패하는지
  확인했다(mutation testing). 하나(큐를 재구성마다 새로 만드는 변형)는 경합이라 3번 중 2번만 잡힌다 —
  `test_reconfigure_loses_nothing_logged_concurrently`에 그렇게 적어 뒀다.
- **예제 ex09**: 사용자가 별도로 요청. 싱크별 필터링, `[log.levels]`로 시끄러운 로거 누르기,
  `log.exception()`의 `exc` 필드, `task` 필드가 어느 태스크에서 왔는지, `instance_id`로 로그 파일
  거르기를 한 화면에서 보인다.
- **문서 재배치**: 사용자 요청으로 `TODO.md`·`HANDOFF.md`를 `docs/`로 옮기고 설계 문서도 처음부터
  거기 두었다. `AGENTS.md`의 경로·개수·표를 그때그때 맞췄다(이번 세션 마지막에 한 번 더 정리함 —
  아래 "이번 세션에서 정리한 문서" 참고).

## 이번 세션에서 정리한 문서

사용자가 "새 세션 시작 준비" 겸 문서 정리를 요청해서 함께 했다.

- `docs/HANDOFF.md`: 이 파일을 이번 인수인계로 새로 썼다. 직전 버전의 안건 중 아직 유효한 예외
  정책(TODO 1·8)은 아래 "사용자 결정 대기"에 옮겨 왔다.
- `docs/TODO.md`: 10번 본문 속에 묻혀 있던 미완료 항목(로그서버 전송, `print` 이관)을 **11번·12번
  으로 승격**했다. 묻힌 채로 두면 10번이 `[해결]`이라 다음 세션이 지나칠 위험이 있었다. 1번은
  8번과 같은 주제인데 너무 짧아서 "8번 참고"를 붙였다. 헤더의 열린 과제 안내도 1·8·11·12로 갱신.
- `AGENTS.md`: 새 "새 세션을 시작할 때" 절을 프로젝트 개요 바로 다음에 추가해 `docs/HANDOFF.md` →
  `docs/TODO.md` 순으로 읽으라고 명시했다. "현재 저장소 상태"의 날짜(9/21→9/22)와 작업 브랜치
  (`main`→`feat/log`)를 갱신하고, 로그 모듈 항목이 11·12번을 가리키게 고쳤다.

## 사용자 결정 대기

1. **TODO 1·8 예외 정책** — 여전히 미정이라 구현하지 말 것. 사용자에게 제시한 선택지:
   1. 로그만 남기고 계속 — 정리는 항상 끝나지만 오류를 놓치기 쉽다.
   2. **정리를 끝까지 한 뒤 모은 오류를 `ExceptionGroup`으로 재발생** — (추천) 정리 보장 +
      호출자도 오류를 본다. 현재 `TaskGroup` 스타일과 맞는다.
   3. 스테이지별 실패 콜백 — 가장 유연하지만 API가 늘어난다.

   추천안에 덧붙인 것: **`SendRouter`에서 Sender 하나의 실패를 격리**해 공유 generator가 죽지 않게.

   손댈 자리(함수 이름 기준, `src/trading_core/`):
   - `domain.py` `_define_inst_stage()`의 `unbind_symbols()`·`detach()` — `unbind_cb`·`detach_cb`가
     `TaskGroup`/`await` 안에서 던지면 `detach()`가 중간에 끊겨 상위가 안 내려가고
     `stage.update`/`detach` 교체도 안 된다.
   - `domain.py` 원천 스테이지 `update()`들의 `bind_pack._detach_cb` 호출, generate 콜백의 `finally`.
   - `domain.py` `SendRouter.__call__` — `TaskGroup` 안에서 Sender 하나가 던지면 전체가 실패.
   - `domain.py` `_task_sequence()` — `seq.invoke()`가 던지면 슬롯 태스크가 조용히 죽는다.
   - `helper.py` `TaskManager._task_wrapper()` / `on_task_failure()` — 현재 태스크 예외 처리 지점.
2. **로그서버 실제 전송(TODO 11)** — `ServerSink.send_batch()`가 `NotImplementedError`다. 프로토콜(HTTP?
   WebSocket? UDP?), 재시도·백오프, `flush_interval` 타이머는 실제로 붙일 로그서버가 정해지면
   같이 정한다. `docs/design.log.md` 7절·"미결 사항" 참고.
3. **기존 `print`를 로그 모듈로 옮기는 일(TODO 12)** — `helper.py`(`TaskManager`의 `[TASK ...]` 진단)와
   `domain.py`(경고 하나)에 `print`가 남아 있다. 이번 설계·구현 범위에서 의도적으로 뺐다
   (`docs/design.log.md` "비목표"). 옮길지, 옮긴다면 로그 레벨을 뭘로 할지 사용자와 정할 것.

## 작업 규칙 (계속 유효)

- 새 불변식을 테스트로 덮으면 수정을 되돌려 그 테스트만 깨지는지 확인한다(mutation testing).
  이번 세션은 로그 모듈 8개 동작 전부에 이 방식을 적용했다.

## 알아 둘 함정

- 커밋된 파일에 `git stash push <file>`을 하면 아무것도 안 하고 "No stash entries"로 끝난다.
  수정 전 코드로 되돌려 시험할 때는 파일을 스크래치에 복사해 두고 되돌리는 편이 안전하다.
- `test_logger.py`는 **프로세스 전역인 루트 로거**를 건드린다. autouse 픽스처가 CWD·환경변수를
  격리하고 `shutdown()`으로 되돌리지만, 이 파일을 고칠 때 다른 테스트 파일과 병렬로 돌리는
  러너를 쓰면 상태가 섞일 수 있다(`pytest`는 기본으로 순차 실행이라 지금은 문제없다).
- TODO 9 같은 경합은 통합 테스트로는 확률적으로만 드러난다. 재현이 잘 안 될 때는 문제의
  타이밍을 단위 테스트로 직접 만드는 편이 낫다(`test_transport.py`,
  `test_reconfigure_loses_nothing_logged_concurrently`가 그 예).
- 테스트는 요청의 `tag`(모델 테스트) 또는 로거 이름(로그 테스트)으로 격리한다. 새 테스트는
  기존과 겹치지 않는 값을 쓸 것.
