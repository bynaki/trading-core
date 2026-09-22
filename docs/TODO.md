# TODO

> 우선순위: **10번(로그 모듈)이 최우선**이다. 1·8번은 사용자 결정 대기로 보류 중이다.

1. TaskManager: task에서 예외가 발생했을때 TaskManager 단에서 처리 방법

2. [해결] 같은 파생 요청을 서로 다른 심볼 집합으로 동시에 구독하면 먼저 구독한 쪽이 데이터를 전혀 받지 못하던 문제.
   파생 스테이지 자신의 심볼은 SharedSender가 합집합으로 관리하는데, 상위 원천에 등록하는 심볼은 그 시점 update의 req_symbols뿐이라 같은 transq의 이전 등록을 덮어쓰고 있었다. require 변환을 set_sender() 뒤로 옮겨 합집합(current_symbols)을 입력으로 쓰도록 고쳤다.
   재현·검증: examples/ex05 (README에 내력), tests/test_domain.py의 `test_dependent_registers_the_union_upstream`.

   남은 제약: require 콜백이 심볼에 따라 다른 상위 요청을 반환하는 것은 여전히 불가능하다. 파생 스테이지가 transq 하나로 상위 하나만 바라보기 때문이며, 필요해지면 상위 스테이지를 여러 개 드는 구조가 따로 있어야 한다.

3. [해결] instanter(RequestModel) 경로가 한 번도 실행된 적이 없어 `Domain._define_inst_stage()`에 결함 셋이 남아 있던 문제. ex07이 이 경로를 쓰는 첫 예제라 거기서 드러났다.
   (1) `new_symbols`를 센티널이 섞인 `current_symbols`에서 계산해 `"__require__"`가 실제 심볼처럼 bind 콜백에 넘어갔다(require까지 쓰면 같은 태스크 이름이 두 번 제출된다). 원본 `symbols`에서 계산하도록 고쳤다.
   (2) `Registered`가 가변 pydantic 모델을 품은 채 `set`에 들어가 `TypeError`가 났다. `SendRouterSet`을 content_id 키의 dict로 바꿨다. `BaseReqModel`은 `__setattr__`로 content_id 캐시를 무효화하는 가변 모델이므로 hashable로 만들면 안 된다.
   (3) 상위 스테이지에 시퀀스가 요구한 상위 표기(`seq.symbol`)가 아니라 소비자가 구독한 하위 심볼을 등록했다. 상·하위 표기가 같은 요청이면 증상이 안 보이는 잠복 버그였다. `reg.router.symbols`를 쓰도록 고쳤다.
   재현·검증: examples/ex07, tests/test_domain.py의 `instanter 스트림` 절(테스트 셋 모두 표기가 다른 매핑을 써야 (3)이 잡힌다).

4. [해결] `Sequence._set_req_symbol()`이 쓰는 `_req_symbol`은 binder.py에서 쓰기만 하고 어디서도 읽지 않는 죽은 속성이었다. 지웠다.
   그 값(하위 슬롯 키)은 `_define_inst_stage.update()`가 이미 `seq_sender_dict`/`transq_dict`의 **키**로 들고 있어 중복이었다. `unbind_cb`도 그 키로 부르므로, 시퀀스를 손에 들고 슬롯 키를 모르는 자리는 없다. 6번을 고칠 때도 `transq_dict.keys()`면 된다.
   게다가 binder의 wrap을 거친 시퀀스에만 생기고 `__init__`에 선언이 없어서, `req(symbol)`로 직접 만든 `RequireSequence`에는 속성 자체가 없었다. 읽히지 않는 속성이 아니라 읽으면 `AttributeError`가 나는 함정이었다.
   부수 효과: `set_bind_cb()`/`set_require_cb()`의 wrap이 순수 통과가 되어 함께 사라졌다(`self._bind_cb = cb`). 제너레이터 래핑이 한 겹 줄었다. `get_generate_cb()`/`get_dependent_cb()`의 wrap은 `_tr_req_content_id`를 심으므로 남는다.

5. [해결] 어떤 시퀀스도 쓰지 않게 된 상위 스테이지가 instanter의 `active_stage_set`에 계속 남던 문제.
   `SendRouterSet.clear()`가 센더가 다 빠진 `Registered`를 남겨 그 상위가 `detaching_stage_set`에 걸리지 않았다. 처음엔 "원천 구독이 정상 해제되니 실동작은 무해"로 봤지만 틀렸다. 남은 상위는 이후 `update()`마다 빈 집합으로 `update()`되는데, 원천 스테이지가 이미 사라졌으면 `_define_origin_gen_stage()`가 **원천을 새로 만들어 init 콜백을 부르고 곧바로 detach**한다. 즉 상위 컨텍스트(연결 등)가 갱신마다 열렸다 닫혔다. 심볼마다 다른 상위를 쓰는 요청에서 드러난다.
   `SendRouterSet.prune()`을 두어 다시 채운 뒤 센더 없는 항목을 지우고, 그 상위는 같은 `update()`에서 떼어 내도록 했다. 항목이 무한히 쌓이는 것도 함께 막힌다. 떼어 낸 상위가 나중에 다시 쓰이면 새 `SendRouter`와 새 스테이지가 짝지어지므로 동일성 검사와 충돌하지 않는다.
   재현·검증: tests/test_domain.py의 `test_instant_detaches_an_upstream_no_sequence_uses`(`SplitReq`).

6. [해결] instanter 스테이지의 `detach()`가 남아 있는 심볼에 대해 `unbind_cb`를 부르지 않아, 심볼을 들고 종료하는 보통의 경우에 심볼별 자원이 새던 문제.
   심볼 단위 정리를 `unbind_symbols()` 지역 헬퍼로 뽑아 `update()`의 삭제 경로와 `detach()`가 함께 쓰도록 했다. 이제 계약은 "`bind_cb`로 연 심볼은 어느 경로로 닫히든 `unbind_cb` 한 번"이다. `update()`가 이미 `transq_dict`에서 pop 하므로 이중 호출은 구조적으로 막힌다.
   `"__require__"`는 `req_cb`가 만든 슬롯이라 bind된 적이 없으므로 제외한다. `update()` 쪽도 센티널이 `del_symbols`에 들어가지 않으므로 두 경로가 여기서도 같다.
   재현·검증: tests/test_domain.py의 `test_instant_detach_unbinds_remaining_symbols`(정리 누락), `test_instant_unbinds_each_symbol_exactly_once`(짝 계약), `test_instant_require_slot_is_not_unbound`(센티널 제외).

7. [해결] instanter에서 심볼을 뺐다가 곧바로 다시 넣으면 `f"{id}:{symbol}"` 태스크 이름 충돌로 `TaskManagerError`가 나던 문제.
   슬롯을 닫을 때 `transq.shutdown()`만 하고 `_task_sequence` 종료를 기다리지 않았다. 소비자(`output`)가 느려 태스크가 `await sender(...)`에 묶여 있으면 큐를 닫아도 끝나지 않으므로, 이 경우 재구독은 확정적으로 실패했다(소비자가 빠르면 우연히 통과한다).
   슬롯 닫기를 `close_slots()` 지역 헬퍼로 뽑아 큐를 닫은 뒤 `cancel_by_name()`으로 이름 해제까지 기다리게 했다. `unbind_symbols()`와 `detach()`의 `"__require__"` 슬롯 정리가 함께 쓴다. 닫힌 슬롯에 남은 데이터는 버려지고, `unbind_cb`는 슬롯 태스크가 끝난 뒤에 불린다.
   재현·검증: tests/test_domain.py의 `test_instant_symbol_can_be_resubscribed_right_away`(느린 소비자를 흉내 내는 `BlockingRecorder` 사용).

8. 사용자 콜백이 예외를 던질 때의 정책이 없다. `unbind_cb`·`detach_cb`가 `TaskGroup` 안에서 던지면 `detach()`가 중간에 끊겨 상위 스테이지가 안 내려가고 `stage.update`/`detach` 교체도 안 된다. generate 콜백의 `finally`도 같은 노출을 갖는다. 1번과 같은 주제이므로 함께 정해야 한다.

9. [해결] instanter 슬롯이 닫힐 때 공유된 상위 generator가 죽을 수 있던 경합.
   `update()`는 빠지는 슬롯의 큐를 먼저 닫고 상위 구독은 나중에 갱신한다. 그 사이 상위가 보낸 데이터가 `SequenceSender`에서 `ClosedConnection`으로 터지면 `SendRouter`의 `TaskGroup`을 거쳐 원천 generator 태스크가 죽었다. 같은 상위 심볼을 다른 소비자(예: content_id가 같은 두 요청형 스테이지, ex08)가 계속 구독 중이면 합집합이 그대로라 재시작되지 않고, 그 소비자는 영영 데이터를 못 받는다. 7번 이전부터 있던 경합이다(재현 시나리오 기준 약 절반 확률).
   닫힌 슬롯은 받을 소비자가 없으므로 `SequenceSender`가 `ClosedConnection`을 삼키도록 했다. 일반적인 "Sender 하나의 실패가 공유 generator를 죽인다"는 문제는 1·8번의 예외 정책에 남는다.
   재현·검증: tests/test_transport.py의 `test_sequence_sender_drops_data_for_a_closed_slot`(경합이라 통합 테스트 대신 단위로 고정).

10. 프로젝트 전반 로그 모듈(`logger.py`) 구현. 설계는 `docs/design.log.md`에 있다. `setting.toml`의
    `[log]` 카테고리로 콘솔·파일·로그서버(자리만, 아직 미구현) 스위치를 설정한다. 여러 서버에 같은
    코드가 뜨는 배포를 대비해 레코드마다 `service`/`host`/`pid`/`instance_id`로 발신처를 구분한다.
    구현 시 `tests/test_logger.py`를 새로 추가한다.
