# 인수인계 (2026-09-21)

새 세션은 이 문서부터 읽는다. 프로젝트 전반의 안내는 `AGENTS.md`(`CLAUDE.md`가 참조)에 있고,
과제의 내력은 `TODO.md`에 있다. 이 문서는 **직전 세션이 어디서 멈췄는지**만 다룬다.
일을 이어받아 끝내면 이 문서는 지워도 된다.

## 지금 상태

- 브랜치 `main`, 작업 트리 깨끗함. **`origin/main`보다 5커밋 앞서 있고 push하지 않았다.**
- ruff check · format · pyright(0 errors) · pytest(90 passed) 모두 통과.
  `uv run examples/main.py serial`과 `parallel` 모두 ex01~ex08 완주, 오류 없음.

push 대기 중인 커밋:

| 커밋 | 내용 |
| --- | --- |
| `e3fdad8` docs | 병합 완료된 저장소 상태와 TODO 2번의 테스트 참조를 현행으로 |
| `003fcea` fix | TODO 7 — instanter 슬롯을 닫을 때 태스크 이름 해제까지 기다리기 |
| `91ae02f` fix | TODO 5 · TODO 9 — 안 쓰이게 된 상위 떼어 내기, 닫힌 슬롯이 공유 상위를 죽이지 않게 |
| `4192739` docs | "커밋 전에 검증하고 사용자에게 묻는다" 규칙 추가 |
| `fb1811e` docs | 에이전트 안내를 `AGENTS.md`로 옮기고 `CLAUDE.md`는 `@AGENTS.md` 한 줄만 |

## 직전 세션에서 고친 것 (요약)

자세한 내력은 `TODO.md` 5·7·9번에 있다.

- **TODO 7** — 소비자가 느리면 슬롯 태스크가 `await sender(...)`에 묶여, 큐를 닫아도 이름
  `{id}:{symbol}`이 풀리지 않았다. 같은 심볼을 곧바로 재구독하면 `TaskManagerError`.
  → `_define_inst_stage()` 안에 `close_slots()`를 두어 `cancel_by_name()`으로 이름 해제까지 대기.
- **TODO 5** — 어떤 시퀀스도 안 쓰게 된 상위가 `active_stage_set`에 남아, 이후 `update()`마다
  빈 집합으로 갱신되며 **원천이 새로 만들어졌다(init) 곧바로 정리(detach)**되었다.
  "실동작 무해"라던 기존 판단은 틀렸다. → `SendRouterSet.prune()`.
- **TODO 9 (새로 발견)** — 슬롯은 상위 구독 갱신보다 먼저 닫힌다. 그 사이 온 데이터가
  `ClosedConnection`으로 `SendRouter`의 `TaskGroup`을 타고 올라가 **공유 상위 generator가 죽었다.**
  다른 소비자가 같은 상위 심볼을 쓰고 있으면 합집합이 그대로라 재시작되지 않는다(원래부터 있던 경합).
  → `SequenceSender.__call__`이 `ClosedConnection`을 삼킨다.

새 테스트: `test_instant_symbol_can_be_resubscribed_right_away`(`BlockingRecorder` 사용),
`test_instant_detaches_an_upstream_no_sequence_uses`(`SplitReq` 사용),
`test_transport.py`의 `test_sequence_sender_drops_data_for_a_closed_slot`.
셋 다 해당 수정만 되돌리면 그 테스트 하나만 깨지는 것을 확인했다.

## 사용자 결정 대기

1. **push 여부** — 위 5커밋을 `origin/main`에 올릴지. 묻지 않고 push하지 말 것.
2. **TODO 1·8 예외 정책** — 정해지기 전에는 구현하지 말 것. 사용자에게 제시한 선택지:
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

## 작업 규칙 (이번 세션에서 확정된 것)

- **커밋·push 전에 검증하고 사용자 승인을 받는다.** 검증 결과와 커밋할 파일·메시지를 보여 주고
  승인 후에만 커밋한다. 계획 승인은 커밋 승인이 아니다. (`AGENTS.md` "코드 규약")
- 새 불변식을 테스트로 덮으면 수정을 되돌려 그 테스트만 깨지는지 확인한다.

## 알아 둘 함정

- 커밋된 파일에 `git stash push <file>`을 하면 아무것도 안 하고 "No stash entries"로 끝난다.
  수정 전 코드로 되돌려 시험할 때는 파일을 스크래치에 복사해 두고 되돌리는 편이 안전하다.
- TODO 9 같은 경합은 통합 테스트로는 약 절반 확률로만 재현된다. 재현용 탐침(두 `SwingReq`
  스테이지가 같은 `BTC`를 구독하고 한쪽이 빠졌다 들어오기를 반복)은 단위 테스트로 대체하고 지웠다.
- 테스트는 요청의 `tag`로 격리한다. 새 테스트는 다른 테스트와 겹치지 않는 `tag`를 쓸 것.
