# TODO

1. TaskManager: task에서 예외가 발생했을때 TaskManager 단에서 처리 방법

2. [해결] 같은 파생 요청을 서로 다른 심볼 집합으로 동시에 구독하면 먼저 구독한 쪽이 데이터를 전혀 받지 못하던 문제.
   파생 스테이지 자신의 심볼은 SharedSender가 합집합으로 관리하는데, 상위 원천에 등록하는 심볼은 그 시점 update의 req_symbols뿐이라 같은 transq의 이전 등록을 덮어쓰고 있었다. require 변환을 set_sender() 뒤로 옮겨 합집합(current_symbols)을 입력으로 쓰도록 고쳤다.
   재현·검증: examples/ex05 (README에 내력), tests/test_ex05.py.

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

5. `SendRouterSet.clear()`가 센더가 다 빠진 `Registered`를 남기므로, 해당 스테이지가 `active_stage_set`에 계속 남는다(`detaching_stage_set`에 걸리지 않는다). 지금은 `update(set())`을 받아 원천 구독이 정상 해제되고 나중 `detach()`도 무해한 no-op이라 실동작 문제는 없지만, 스테이지 수명이 실제 구독보다 길다는 점은 남아 있다.

6. instanter 스테이지의 `detach()`가 남아 있는 심볼에 대해 `unbind_cb`를 부르지 않는다. `update()`로 심볼이 빠질 때는 부르므로, 정리 경로 둘이 서로 다르게 동작한다.
