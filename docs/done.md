# Done

> `docs/plan.md`에서 완료되고, 남은 열린 과제와 관련이 없어진 항목을 여기로 옮긴다. 새 세션은
> 이 파일을 매번 읽지 않는다 — 과거 결함·설계 결정의 내력이 필요할 때만 찾아본다. 형식은
> `docs/plan.md`와 같다(`AGENTS.md` "새 세션을 시작할 때" 참고).

### [done] domain:dependent-union-share
같은 파생 요청을 서로 다른 심볼 집합으로 동시에 구독하면 먼저 구독한 쪽이 데이터를 전혀 받지
못하던 문제. 파생 스테이지 자신의 심볼은 SharedSender가 합집합으로 관리하는데, 상위 원천에
등록하는 심볼은 그 시점 update의 req_symbols뿐이라 같은 transq의 이전 등록을 덮어쓰고 있었다.
require 변환을 set_sender() 뒤로 옮겨 합집합(current_symbols)을 입력으로 쓰도록 고쳤다.
재현·검증: examples/ex05(README에 내력), tests/test_domain.py의 `test_dependent_registers_the_union_upstream`.

남은 제약: require 콜백이 심볼에 따라 다른 상위 요청을 반환하는 것은 여전히 불가능하다. 파생
스테이지가 transq 하나로 상위 하나만 바라보기 때문이며, 필요해지면 상위 스테이지를 여러 개 드는
구조가 따로 있어야 한다.

### [done] domain:instanter-bootstrap
instanter(RequestModel) 경로가 한 번도 실행된 적이 없어 `Domain._define_inst_stage()`에 결함 셋이
남아 있던 문제. ex07이 이 경로를 쓰는 첫 예제라 거기서 드러났다.
(1) `new_symbols`를 센티널이 섞인 `current_symbols`에서 계산해 `"__require__"`가 실제 심볼처럼
bind 콜백에 넘어갔다(require까지 쓰면 같은 태스크 이름이 두 번 제출된다). 원본 `symbols`에서
계산하도록 고쳤다.
(2) `Registered`가 가변 pydantic 모델을 품은 채 `set`에 들어가 `TypeError`가 났다. `SendRouterSet`을
content_id 키의 dict로 바꿨다. `BaseReqModel`은 `__setattr__`로 content_id 캐시를 무효화하는 가변
모델이므로 hashable로 만들면 안 된다.
(3) 상위 스테이지에 시퀀스가 요구한 상위 표기(`seq.symbol`)가 아니라 소비자가 구독한 하위 심볼을
등록했다. 상·하위 표기가 같은 요청이면 증상이 안 보이는 잠복 버그였다. `reg.router.symbols`를
쓰도록 고쳤다.
재현·검증: examples/ex07, tests/test_domain.py의 `instanter 스트림` 절(테스트 셋 모두 표기가
다른 매핑을 써야 (3)이 잡힌다).

### [done] model:dead-attribute
`Sequence._set_req_symbol()`이 쓰는 `_req_symbol`은 binder.py에서 쓰기만 하고 어디서도 읽지 않는
죽은 속성이었다. 지웠다.
그 값(하위 슬롯 키)은 `_define_inst_stage.update()`가 이미 `seq_sender_dict`/`transq_dict`의
**키**로 들고 있어 중복이었다. `unbind_cb`도 그 키로 부르므로, 시퀀스를 손에 들고 슬롯 키를 모르는
자리는 없다.
게다가 binder의 wrap을 거친 시퀀스에만 생기고 `__init__`에 선언이 없어서, `req(symbol)`로 직접
만든 `RequireSequence`에는 속성 자체가 없었다. 읽히지 않는 속성이 아니라 읽으면 `AttributeError`가
나는 함정이었다.
부수 효과: `set_bind_cb()`/`set_require_cb()`의 wrap이 순수 통과가 되어 함께 사라졌다
(`self._bind_cb = cb`). 제너레이터 래핑이 한 겹 줄었다. `get_generate_cb()`/`get_dependent_cb()`의
wrap은 `_tr_req_content_id`를 심으므로 남는다.

### [done] domain:instanter-orphan-upstream
어떤 시퀀스도 쓰지 않게 된 상위 스테이지가 instanter의 `active_stage_set`에 계속 남던 문제.
`SendRouterSet.clear()`가 센더가 다 빠진 `Registered`를 남겨 그 상위가 `detaching_stage_set`에
걸리지 않았다. 처음엔 "원천 구독이 정상 해제되니 실동작은 무해"로 봤지만 틀렸다. 남은 상위는
이후 `update()`마다 빈 집합으로 `update()`되는데, 원천 스테이지가 이미 사라졌으면
`_define_origin_gen_stage()`가 **원천을 새로 만들어 init 콜백을 부르고 곧바로 detach**한다. 즉
상위 컨텍스트(연결 등)가 갱신마다 열렸다 닫혔다. 심볼마다 다른 상위를 쓰는 요청에서 드러난다.
`SendRouterSet.prune()`을 두어 다시 채운 뒤 센더 없는 항목을 지우고, 그 상위는 같은 `update()`에서
떼어 내도록 했다. 항목이 무한히 쌓이는 것도 함께 막힌다. 떼어 낸 상위가 나중에 다시 쓰이면 새
`SendRouter`와 새 스테이지가 짝지어지므로 동일성 검사와 충돌하지 않는다.
재현·검증: tests/test_domain.py의 `test_instant_detaches_an_upstream_no_sequence_uses`(`SplitReq`).

### [done] domain:instanter-detach-unbind
instanter 스테이지의 `detach()`가 남아 있는 심볼에 대해 `unbind_cb`를 부르지 않아, 심볼을 들고
종료하는 보통의 경우에 심볼별 자원이 새던 문제.
심볼 단위 정리를 `unbind_symbols()` 지역 헬퍼로 뽑아 `update()`의 삭제 경로와 `detach()`가 함께
쓰도록 했다. 이제 계약은 "`bind_cb`로 연 심볼은 어느 경로로 닫히든 `unbind_cb` 한 번"이다.
`update()`가 이미 `transq_dict`에서 pop 하므로 이중 호출은 구조적으로 막힌다.
`"__require__"`는 `req_cb`가 만든 슬롯이라 bind된 적이 없으므로 제외한다. `update()` 쪽도 센티널이
`del_symbols`에 들어가지 않으므로 두 경로가 여기서도 같다.
재현·검증: tests/test_domain.py의 `test_instant_detach_unbinds_remaining_symbols`(정리 누락),
`test_instant_unbinds_each_symbol_exactly_once`(짝 계약), `test_instant_require_slot_is_not_unbound`
(센티널 제외).

### [done] domain:instanter-resubscribe
instanter에서 심볼을 뺐다가 곧바로 다시 넣으면 `f"{id}:{symbol}"` 태스크 이름 충돌로
`TaskManagerError`가 나던 문제.
슬롯을 닫을 때 `transq.shutdown()`만 하고 `_task_sequence` 종료를 기다리지 않았다. 소비자(`output`)가
느려 태스크가 `await sender(...)`에 묶여 있으면 큐를 닫아도 끝나지 않으므로, 이 경우 재구독은
확정적으로 실패했다(소비자가 빠르면 우연히 통과한다).
슬롯 닫기를 `close_slots()` 지역 헬퍼로 뽑아 큐를 닫은 뒤 `cancel_by_name()`으로 이름 해제까지
기다리게 했다. `unbind_symbols()`와 `detach()`의 `"__require__"` 슬롯 정리가 함께 쓴다. 닫힌 슬롯에
남은 데이터는 버려지고, `unbind_cb`는 슬롯 태스크가 끝난 뒤에 불린다.
재현·검증: tests/test_domain.py의 `test_instant_symbol_can_be_resubscribed_right_away`(느린
소비자를 흉내 내는 `BlockingRecorder` 사용).

### [done] domain:instanter-closed-slot-race
instanter 슬롯이 닫힐 때 공유된 상위 generator가 죽을 수 있던 경합.
`update()`는 빠지는 슬롯의 큐를 먼저 닫고 상위 구독은 나중에 갱신한다. 그 사이 상위가 보낸
데이터가 `SequenceSender`에서 `ClosedConnection`으로 터지면 `SendRouter`의 `TaskGroup`을 거쳐
원천 generator 태스크가 죽었다. 같은 상위 심볼을 다른 소비자(예: content_id가 같은 두 요청형
스테이지, ex08)가 계속 구독 중이면 합집합이 그대로라 재시작되지 않고, 그 소비자는 영영 데이터를
못 받는다. domain:instanter-resubscribe 이전부터 있던 경합이다(재현 시나리오 기준 약 절반 확률).
닫힌 슬롯은 받을 소비자가 없으므로 `SequenceSender`가 `ClosedConnection`을 삼키도록 했다. 일반적인
"Sender 하나의 실패가 공유 generator를 죽인다"는 문제는 policy:callback-exception(`docs/plan.md`)에
남는다.
재현·검증: tests/test_transport.py의 `test_sequence_sender_drops_data_for_a_closed_slot`(경합이라
통합 테스트 대신 단위로 고정).

### [done] logger:print-migration
기존 `print`를 로그 모듈로 옮겼다. `helper.py`의 `TaskManager`(`[TASK SUBMIT]` 등 진단, 여러 곳)와
`domain.py`의 `SendRouter.__call__`에 있던 경고 한 줄("Sender가 없다")이 대상이었다.
`helper.py`·`domain.py`는 각각 모듈 상단에서 `get_logger(__name__)`으로 로거를 얻는다(순환 임포트
없음, `docs/log.spec.md` "비목표" 참고). 정한 레벨: `TaskManager`의 제출·완료·취소·예외 훅은 모두
DEBUG(진단), `SendRouter`의 "Sender가 없다"는 WARNING. `on_task_exception`은 `exc_info=exc`로 예외
정보를 함께 싣는다.
재현·검증: `uv run examples/main.py serial` — ex09 로그 요약(`로거별`)에 `trading_core.helper`
레코드가 잡힌다. 전용 단위 테스트는 없다(레벨·메시지 문구는 불변식이 아니라서).

### [done] examples:logger-output
예제 출력을 `print`에서 로그 모듈로 옮기고 보기 쉽게 정리했다. 공용 설정은 `examples/setting.toml`
(콘솔 text.simple·stdout·INFO)이고 `main.py`와 각 `run_ex.py`의 `main()`이 `configure()`한다.
로거 이름은 예제·계층별로 직접 준다(`ex05.origin`·`ex05.require`·`ex05.dependent`, 소비자는
`ex05`). 그래서 `parallel`에서도 줄마다 어느 예제의 어느 부분인지 보인다.
`model_dump_json(indent=2)` 덤프는 한 줄 fields로 바꿨고, 판정의 `회귀:`는 ERROR로 남긴다. 예제마다
`━━━━ 시작 ━━━━`/`━━━━ 끝 ━━━━` 배너를 두고, 끝 배너 메시지를 `"\n"`으로 끝내 예제 사이에 빈 줄을
남긴다(로그로는 빈 줄을 따로 못 찍는다). ex09는 끝에 `shutdown()` 대신 공용 설정으로 재구성한다.
`shutdown()` 뒤에는 자동 구성이 없어 이어서 도는 예제의 로그가 사라지기 때문이다.
로그 모듈 쪽에는 콘솔 형식 `"text.simple"`(시각과 `[service@host:pid]`를 뺀
`INFO  ex05.origin: ...`)을 더해 예제 공용 설정이 쓴다. ex09 전용 설정은 발신처를 보여야 하므로
`"text"`로 둔다. 두 text 형식은 fields가 60자(`_INLINE_FIELDS_MAX`)를 넘으면 한 블록으로, dict
값은 이름을 달아 indent=2 JSON으로 아래 줄에 펼친다.
재현·검증: `uv run examples/main.py serial`·`parallel`. 형식 규칙은 tests/test_logger.py의
`test_console_simple_text_format_drops_time_and_origin`, `test_text_fields_*` 세 개.

### [done] naming:rename
모듈·클래스·메서드·변수·타입 이름을 목적과 의미에 맞게 바꿨다. 1~33번 전부 적용했고, 목록과
적용하며 달라진 점은 `docs/naming.spec.md`에 있다. 요청 3종이 `SourceRequest`/`DerivedRequest`/
`SessionRequest`가 되고, `Domain`의 공개 API가 `subscribe()`/`stream()`/`Subscription`/
`get_shared_symbols()`로 바뀌었다. 직렬화 형식(모델 타입 리터럴, `tr_annotation`의 `uid`·`created_by`
키)도 바뀌었으므로 옛 형식으로 저장한 덤프는 `load_model()`로 되살릴 수 없다.

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

### [done] policy:symbol-failure
원천은 심볼 합집합 하나로 돌아서, 한 소비자가 넣은 잘못된 심볼(상장 폐지·오타) 때문에 binder가 던지면
같은 원천을 쓰는 모든 소비자가 실패했다. 이제 binder가 원천·파생 generator에서
`raise SymbolRejected(symbols, reason)`을 던지면, 코어가 피해를 그 심볼로 좁힌다(`AGENTS.md` 핵심 불변식 7).

정한 것(사용자가 오류를 신경 쓰지 않게 Domain이 다 처리한다는 방향):
- **binder가 하는 일은 어느 심볼을 줄 수 없는지 던지는 것뿐이다.** 거래소 오류 응답에서 심볼을 읽어
  낼 수 있는 것은 binder뿐이라 이 한 줄은 남는다. Domain이 일반 예외에서 범인 심볼을 찾는 방법(반씩
  나눠 재시작)은 스테이지 전체의 실패를 심볼 탓으로 돌리고 재시도 금지와 부딪쳐 버렸다.
- **`yield`가 아니라 `raise`다.** `yield SymbolRejected`안은 재연결이 없지만, binder가 거부한 심볼을
  직접 걸러 내야 하고(빼먹으면 경고만 쌓인다) yield 타입이 넓어지며 활성 심볼 집합을 재시작 없이 고치는
  예외 경로가 생긴다. 재시작은 소비자가 심볼을 바꿀 때마다 이미 일어나므로 binder는 원래 재시작을
  견딘다. 재연결 비용이 문제가 되면 `yield`를 확장으로 더할 수 있다(같은 타입을 쓴다).
- 그 심볼만 구독에서 빼(`SymbolRouter.take()`) 구독한 소비자에게 자기 심볼만 알리고, `sync()`가 남은
  심볼로 다시 띄운다(`fail_symbols()`). 남은 심볼이 없으면 스테이지가 내려간다.
- **가드**: 지금 구독된 심볼이 하나도 없는 거부는 스테이지 전체의 실패로 본다. 같은 합집합으로 다시
  띄우면 끝없이 되풀이되거나, 아무것도 다시 띄우지 않아 멈춘다.
- **파생 연쇄**: `on_upstream_fail()`이 스테이지 전체를 내리던 것을 `fail_upstream_symbols()`로 바꿨다.
  하위 심볼마다 `resolve_upstream({s})`로 상위 표기를 구해 실패 집합과 겹치는 하위 심볼만 빼고 남은
  심볼로 다시 띄운다. 모두 겹치면(상위 스테이지 전체 실패·init 실패) 지금처럼 전체가 실패한다. 되돌리지
  못하면(여러 하위 심볼을 상위 하나로 묶는 require) 소리 없이 굶지 않게 전체 실패로 본다.
- 세션은 `on_upstream_failed()`가 원래 상위 표기 심볼 단위로 슬롯을 닫으므로 바꾸지 않았다.
- `stream()`은 심볼 하나의 거부에도 `StageFailed`를 던지고 끝난다(그대로).
재현·검증: tests/test_domain.py의 "심볼 거부" 절 6개. 수정 전 `domain.py`로 돌리면 부분 실패를 보는 4개가
깨지고(나머지 2개는 전체 실패가 기대값), 가드를 빼면 `test_rejecting_only_unsubscribed_symbols_fails_the_stage`가,
파생 되돌리기를 빼면 `test_derived_upstream_rejection_fails_only_the_mapped_symbol`이 깨진다.
예제: ex12가 상장 폐지·오타 심볼·파생 연쇄·세션 슬롯을 판정과 함께 보여 준다. 수정 전 `domain.py`로
돌리면 11개가 회귀로 나온다.
남은 것: 거부된 심볼이 지난 generator에서 왔는지 가리는 세대 검사(`run_seq`)는 기존 경로를 그대로 쓰며
따로 테스트하지 않았다. `StageFailed`의 메시지는 심볼만 실패해도 "스테이지가 실패했다"로 나온다.

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

### [done] domain:request-snapshot
구독한 뒤 요청을 고치면 스테이지가 새던 버그. `_create_shared_subscription()`의 `update`/`detach`가
부를 때마다 `req.tr_content_id`를 다시 계산해, 고친 뒤의 content_id로 스테이지를 찾았다. 처음
스테이지는 아무도 닫지 못한 채(detach 콜백 없이) 떠난 소비자에게 계속 보냈다. `_create_subscription()`이
요청을 `model_copy(deep=True)`로 찍어 두고 `Subscription.request`도 사본을 주게 고쳤다. 세션의 상위
구독은 `request.tr_content_id` 대신 상위 content_id를 키로 찾는다.
재현·검증: `test_mutating_the_request_after_subscribe_does_not_leak_the_stage`,
`test_session_uses_the_request_as_subscribed`(수정을 되돌리면 둘만 깨진다).

### [done] examples:rewrite
처음 배우는 사람이 따라오게 예제를 **기능·사건 하나에 예제 하나**로 다시 쓴다. 정한 것:

- 예제 하나 = 파일 하나, 평평하게(`examples/ex01_stream.py`). 위에서 아래로 모델 → binder → 실행 →
  `main()`. 예제별 README는 없애고 설명은 모듈 docstring(배우는 것·실행·기대 출력 발췌·다음 예제)과
  주석에 둔다. 목차는 `examples/README.md` 하나.
- 정상/회귀 판정표는 없애고 핵심 지점에 `assert`를 둔다(`main.py serial`이 회귀를 여전히 잡는다).
- import는 최상위 `trading_core`에서만. 모의 데이터는 표 대신 계산으로, 발행 간격은 0.2초 안팎.
  `main()`은 늘 `domain.stop()`. `main.py`는 `examples/ex*.py`를 글롭한다.
- 29개로 간다.

| # | 주제 | 출처 |
| --- | --- | --- |
| 01 | 가장 작은 소스 요청 + `Domain.stream()`, start/stop | ex01 |
| 02 | `subscribe()`·Sender, `update()`는 교체, 빈 집합은 해제 | ex03·06 |
| 03 | 두 정리 지점: generator `finally` vs `@detached` (심볼을 바꿔야 갈리므로 02 뒤) | ex01·03 |
| 04 | content_id가 같으면 스테이지·init 하나, 다르면 따로 | ex02·08 |
| 05 | binder엔 합집합, 출력은 구독한 심볼로만 fan-out | ex03·05 |
| 06 | 합집합이 바뀔 때만 재시작, 컨텍스트는 재시작을 넘어 유지 | ex06·03 |
| 07 | `require`(요청만)·`recv()`, 파생 여럿이 소스 스테이지 하나 공유 | ex02 |
| 08 | `require`(심볼까지) 하위→상위 표기, 안 되돌리면 조용히 사라짐 | ex04·05 |
| 09 | 요청 필드로 상위 소스 요청 고르기(심볼별로는 불가) | ex04 |
| 10 | 파생 위의 파생(다단) | 신규 |
| 11 | 세션: bind→`Pipeline`, `Runnable`, 상·하위 표기, `None`으로 거르기 | ex07 |
| 12 | `unbind`·`detached`, bind↔unbind 한 번씩 | ex08 |
| 13 | 같은 content_id라도 세션은 공유 안 됨 | ex08 |
| 14 | 여러 단계 파이프라인 `req(s) \| a \| b \| c` | 신규 |
| 15 | 한 슬롯이 소스 요청 둘을 합치기(bind가 파이프라인 여럿 yield) | 신규 |
| 16 | `@x.always` | 신규 |
| 17 | 소스 generator 실패: 재시도 없음, `StageFailed`, 연쇄, 다시 넣기 | ex10 |
| 18 | Sender 하나의 실패 격리 | ex10 |
| 19 | 정리 콜백 실패해도 정리 끝 | ex10 |
| 20 | `stream()`은 `StageFailed`를 던진다 | ex10 |
| 21 | init 실패(소스 요청, 파생의 상위) | ex11 |
| 22 | 세션 실패(init·bind·파이프라인 단계) → 그 심볼만 | ex11 + 신규 |
| 23 | `always` 실패 → 세션 전체, init부터 다시 | 신규 |
| 24 | `SymbolRejected`(소스·파생·세션 요청) | ex12 |
| 25 | 느린 소비자가 공유 generator를 붙잡는다 → 자기 큐로 떼는 패턴 | 신규 |
| 26 | 등록·사용 실수: `BindError`·`ModelError`·`DomainError`·끊긴 구독 | 신규 + ex11 |
| 27 | 식별자 3종, `compute_tr_content_id`, 가변 모델(구독은 사본) | 신규 |
| 28 | 직렬화: `tr_annotation`·`load_model`·`parse_dump`·`cast_model`·`set_instance_id` | 신규 |
| 29 | 로그 모듈 | ex09 |

순서: 공통 틀 + 1부(01~06)를 먼저 쓰고 형식을 확인받는다 → 2·3부 → 4·5부 → 문서(`examples/README.md`,
루트 README, `AGENTS.md`의 예제 목록·"예제 README" 규칙·테스트 표의 "ex06/ex08 시나리오" 참조) →
검사 4종 + `serial`·`parallel`.

확인한 것: 10·15·16·22(파이프라인 단계가 던짐)·25는 스크래치로 동작을 확인했다. 느린 Sender(건당
0.5초) 하나가 있으면 같은 소스 스테이지의 빠른 소비자가 1.2초에 3건만 받았다(평소 약 24건).

결과: 01~29를 다 썼고 옛 예제 디렉터리(ex01~ex12)를 모두 지웠다. 29는 전용 설정
`examples/ex29_logging.toml`을 쓴다. 목차 `examples/README.md`를 새로 쓰고 루트 README·`AGENTS.md`의
예제 설명과 테스트 docstring의 옛 예제 참조를 고쳤다. 쓰며 안 것:
- 사슬이 내려갈 때 `@detached`는 소스 스테이지부터(아래→위) 불린다(ex10이 출력으로 보인다).
- 되돌리지 않은 파생 데이터는 소비자에게 오류 없이 버려지고 `trading_core.routing` WARNING만 건마다
  남는다(ex08).
- 기대 출력이 실행마다 같도록, 그 예제의 주제가 아닌 재시작 로그(소비자가 붙고 빠질 때 소스
  generator가 다시 뜨는 줄)는 남기지 않는다. 소비자를 `update()`로 연달아 붙이면 먼저 제출된
  generator가 대기 중에 취소되어 한 번만 뜬다.
- 세션 출력은 심볼로 라우팅되지 않고 그 구독의 Sender로 바로 간다. 그래서 세션은 출력 `symbol`을
  되돌리지 않아도 데이터가 사라지지 않는다(파생과 다르다, ex11).
- 세션 bind는 `symbols - active` 집합을 도는 순서라 심볼 여럿을 한 번에 넣으면 bind 순서가 실행마다
  바뀐다. 순서를 보이는 예제(12·15·16)는 심볼을 하나씩 넣는다.
- `stream()`은 첫 데이터를 기다릴 때 구독을 시작한다. 블록에 들어가자마자 `get_shared_symbols()`를 보면
  비어 있다(ex11).
- `log.info(..., **dict)`는 pyright가 `exc_info` 인자와 겹친다고 본다. 키워드를 직접 적는다.
- 실패 예제(17~24)는 코어가 ERROR 로그와 트레이스백을 남긴다. `serial`·`parallel` 확인은 ERROR 줄 수가
  아니라 종료 코드·`AssertionError`·끝난 예제 수로 한다. 단, `on_error`를 준 Sender의 실패(18)는 코어가
  ERROR를 남기지 않는다.
- 소스 스테이지가 실패하면 `@detached`가 "스테이지가 실패했다" ERROR 줄보다 먼저 찍힌다.
- 세션 슬롯 여럿을 함께 닫을 때(구독 끝, always 실패) unbind 순서는 실행마다 바뀐다(19·23).
- 세션 구독이 끝날 때 상위 소스 스테이지의 `@detached`가 세션의 `@detached`보다 먼저 불린다(19).
- `SymbolRejected`는 파생 스테이지에서도 "심볼이 실패해 구독에서 뺐다"로 남고 파생 스테이지는 내려가지
  않는다(24).
- 남긴 후속은 아래 api:export-model-validation-error, api:typed-subscription이다.
- init만 등록하고 generator를 붙이지 않은 요청은 "등록되지 않은 요청"과 같은 `DomainError`다. 요청의
  종류(`_tr_model_type`)가 generator를 등록할 때 정해지기 때문이다(26).
- require가 없는 파생 요청은 `subscribe()`는 지나가고 첫 `update()`에서 `ModelError`다. 스테이지는
  남지 않는다(26).
- 느린 Sender(건당 0.3초) 하나가 있으면 같은 소스 스테이지의 빠른 소비자가 1초에 3건, 자기 큐로 떼면
  20건을 받는다(25). `stream()`의 큐는 크기 제한이 없다.
- `parallel`에서는 29의 파일 집계에 다른 예제의 레코드도 섞인다. 29는 예외 레코드를 자기 로거 이름으로
  고른다.
