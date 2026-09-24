# 이름 정리

모듈·클래스·메서드·변수·타입 이름을 목적과 의미에 맞게 바꾼 내역이다. `docs/DONE.md`의
`naming:rename` 항목이 이 문서를 가리킨다. 3절의 1~33번을 **모두 적용했다.** 적용하면서 계획과
달라진 점은 7절에 있다. 옛 이름에서 새 이름을 찾을 때 이 문서를 본다.

## 1. 왜 바꾸는가

API가 아직 자리 잡는 중이라(README가 일부러 얇다) 이름을 바꾸기 좋은 때다. 코드 전체를 읽어 보면
문제는 세 가지다.

- **한 개념에 이름이 여럿이다.** 원천 하나를 Generate·generator·gen·origin으로 부른다.
- **한 이름이 여러 개념을 떠안았다.** `origin`, `require`, `RequireCb`가 그렇다.
- **이름과 동작이 다르다.** `_define_*`는 실제로 get-or-create이고, `submit_count`는 실제로 살아 있는
  태스크 수다.

## 2. 원칙

- 요청 3종은 **역할이 드러나는 한 규칙**으로 이름 짓는다: 원천(source) · 파생(derived) · 세션(session).
- `Domain`의 공개 API는 **작게** 두고 **내부 객체를 드러내지 않는다.** 사용자가 받는 것은 구독이지
  스테이지가 아니다. 내부 객체가 공개 API에 나오면 계약이 구현 방식에 묶인다.
- 직렬화되어 프로세스 밖으로 나가는 이름(모델 타입 리터럴, `tr_annotation` 키)은 한 번 정하면
  바꾸기 어렵다. 그래서 먼저 확정한다.
- 옛 이름을 남기는 호환 별칭은 두지 않는다. 아직 배포 전 API다.

## 3. 추천 목록

### A. 요청 3종의 이름을 한 규칙으로 맞추기

1. **`GenerateModel` → `SourceRequest`, `DependentModel` → `DerivedRequest`,
   `RequestModel` → `SessionRequest`** (`BaseReqModel` → `BaseRequest`). 지금은 셋 다 요청인데 하나만
   `RequestModel`이라서 이름으로 구분이 안 된다. 원천은 데이터를 가져오고 파생은 변환하며, 둘 다
   content_id가 같으면 스테이지를 공유한다. 세션은 주식 차트 분석에 쓰는 핵심 요청으로, 소비자 하나가
   상태를 가진 채 분석하므로 content_id가 같아도 공유하지 않는다. `SessionRequest`의 docstring에
   "상태를 가지므로 content_id가 같아도 스테이지를 공유하지 않는다(ex08)"를 적는다.
2. **모델 타입 리터럴 `"generator"/"dependent_generator"/"instanter"` → `"source"/"derived"/"session"`.**
   직렬화되는 값이다. "instanter"는 뜻이 전달되지 않는다.
3. **`is_generate_model`/`is_dependent_model`/`is_instant_model` → `is_source`/`is_derived`/`is_session`.**
   지금은 gen/dep/inst 약어가 섞여 있다.
4. **`GenerateModelBinder`/`DependentModelBinder`/`RequestModelBinder` →
   `SourceBinder`/`DerivedBinder`/`SessionBinder`**, 콜백 타입 **`GenerateCb`/`DependentCb` →
   `SourceCb`/`DerivedCb`**.

### B. `Domain` 공개 API: 작게, 내부를 드러내지 않게

5. **`Domain.stage(req, sender)` → `Domain.subscribe(req, sender)`, 핸들 `Stage` → `Subscription`.**
   사용자가 받는 것은 "심볼을 바꾸고(`update`) 끊을 수 있는(`detach`) 구독"이다. 스테이지는 내부
   실행 방식이다. `Stage`라는 말은 내부(`SharedStage` 등)에만 남긴다.
6. **`Domain.request(req, symbols)` → `Domain.stream(req, symbols)`.** 데이터를 흘려주는 async
   generator이고, 5번과 한 짝이다. 요청 모델(`*Request`)과 이름이 겹치지 않는다.
7. **`Subscription`의 속성: `req_model` → `request`, `output` → `sender`.** 인자 이름과 맞춘다.
8. **`get_origin_stage(content_id)` → `get_shared_symbols(content_id) -> set[str]`.** 지금은 내부
   스테이지 객체를 돌려주고, 공유되지 않으면 `KeyError`가 난다. 공유 중인 심볼 합집합만 돌려주고,
   공유되지 않으면 빈 집합을 돌려준다. ex03(합집합 확인)과 ex08(세션 요청은 공유되지 않음)에 둘 다
   충분하다. 테스트도 공개 API만으로 공유 여부를 확인할 수 있다.
9. **`ClosedConnection` → `ChannelClosed`.** 사용자가 만든 `Sender`가 "받는 쪽이 닫혔다"를 알리는
   예외다. 네트워크 연결 이야기가 아니다.

### C. 직렬화 이름: 한 번 정하면 바꾸기 어렵다

10. **프로세스 식별자: `set_origin_name`/`get_origin_name` → `set_instance_id`/`get_instance_id`**,
    어노테이션 `generated_origin` → `created_by`, `get_model_generated_origin` → `get_model_created_by`.
    로그 모듈이 이미 프로세스를 `instance_id`라고 부르므로 같은 말로 맞춘다.
11. **모델 객체 식별자: `get_model_inst_id` → `get_model_uid`**, `_tr_id` → `_tr_uid`, 어노테이션
    `id` → `uid`, `_tr_counter` → `_tr_uid_seq`. "instance"는 10번(프로세스)에 쓴다. 이 값은 프로세스를
    넘어도 유지되는 고유 ID다.
12. **역직렬화 API: `validate_model` → `load_model`, `validate_dump` → `parse_dump`,
    `DataDump` → `ModelDump`, `ModelValidateError` → `ModelValidationError`.** 검증에 그치지 않고 어노테이션으로
    클래스를 찾아 모델을 되살린다. 요청 모델의 덤프도 같은 타입으로 검증하므로 "Data"는 틀린 말이다.

### D. 한 이름이 두 가지 뜻인 경우

13. **`Sequence` → `Pipeline`, `RequireSequence` → `PipelineHead`**, 그리고 `SequenceSender` →
    `PipelineSender`, `_task_sequence` → `_run_pipeline_slot`. `collections.abc.Sequence`와 이름이 겹친다.
    실제로 하는 일도 상위 스트림을 여러 단계에 차례로 통과시키는 파이프라인이다.
14. **`Sequence.require`/`.symbol` → `.upstream`/`.upstream_symbol`.** 상위 표기와 하위 표기의 구분이
    이름에 드러난다. `Registered.require`와 `SendRouterSet.add_sender(req, …)`의 `req`도 `upstream`으로
    바꾼다.
15. **세션 요청의 `@x.require` → `@x.always`**: 타입 `AlwaysCb`, 센티널 `"__require__"` → `"__always__"`,
    변수 `req_cb` → `always_cb`. binder의 `RequireCb`와 model의 `RequireCb`는 서로 다른 타입인데 이름이
    같다. 세션 요청의 것은 "구독 심볼과 상관없이 늘 붙는 파이프라인"이라서, 파생 요청의 `@Req.require`
    (상위 요청 선언)와 뜻이 다르다.
16. **"origin" 정리**: `OriginStage`/`_origin_stage_dict` → `SharedStage`/`_shared_stages`(파생 스테이지도
    들어가므로 "원천"이 아니다), `_tr_origin_annotation` → `_tr_loaded_annotation`(역직렬화로 들어온
    어노테이션), `SequenceSender.origin_sender`는 쓰는 곳이 없어 삭제한다.

### E. 이름과 실제 동작이 다른 경우

17. **`_define_origin_gen_stage`/`_define_origin_dep_stage` →
    `_get_or_create_source_stage`/`_get_or_create_derived_stage`.** 이미 있으면 그걸 돌려주는데, "define"은
    매번 새로 만드는 것처럼 읽힌다. 핸들용 `_define_gen/dep/inst_stage`는
    `_create_source/derived/session_stage`로, `_ensure_require_stage`는 `_ensure_upstream_stage`로 바꾼다.
18. **`TaskManager.submit_count` → `live_count`.** 제출하면 늘고 끝나면 줄어서 제출 횟수가 아니다.
19. **`TaskManager.on_task_failure(cb)` → `set_failure_callback(cb)`.** 다른 `on_task_*`는 재정의하는
    훅인데 이것만 setter다.
20. **`get_tr_content_id()`(매번 계산)와 `_tr_content_id`(캐시) → 공개 캐시 프로퍼티 `tr_content_id` +
    `compute_tr_content_id(include, exclude)`**, `_tr_cached_id` → `_tr_cached_content_id`. 지금은
    `domain.py`가 캐시 없는 쪽만 불러서 캐시가 한 번도 쓰이지 않는다.
21. **`get_tr_require_with_symbol(symbols)` → `resolve_upstream(symbols)`**, `tr_require` → `tr_upstream`.
    이름은 단수 "with_symbol"인데 실제로는 심볼 집합을 받아 변환한다.
22. **`BindPack.get_binder()` → `lookup()`**, `_binder_dict` → `_registry`. 돌려주는 것은 Binder가
    아니라 BindPack이다.
23. **`SendRouter.set_sender(sender, symbols)` → `replace(sender, symbols)`.** "update는 교체다"라는
    불변식과 같은 말을 쓴다.

### F. 모듈·타입·예외

24. **`helper.py`를 `ids.py`(`generate_id`·`generate_digest`·`verify_module`)와 `tasks.py`(`TaskManager`)로
    나눈다.** "helper"라는 이름으로는 안에 뭐가 있는지 알 수 없다.
25. **`TransmitQueue`·`SendRouter`·`SendRouterSet`·`SequenceSender`를 `routing.py`로 옮긴다**
    (`tests/test_transport.py` → `tests/test_routing.py`). `domain.py`에는 `Domain`과 스테이지만 남긴다.
    "transport"는 로그서버 전송(`logger:server-transport`)과 겹친다.
26. **`TransmitQueue` → `Channel`**, 변수 `transq` → `channel`. 프로세스 안의 큐이고, `send`/`recv`/`shutdown`
    인터페이스가 channel이라는 말과 맞는다.
27. **`SendRouter` → `SymbolRouter`, `SendRouterSet` → `UpstreamRouters`, `Registered` → `UpstreamRoute`**,
    `SendRouterSet.__call__`(제너레이터) → `__iter__`.
28. **`TaskManagerError`를 `exceptions.py`로 옮긴다.** 주석에서만 쓰이는 `SequenceError`는 삭제한다.

### G. 인자·지역 변수

29. `BindPack.request_t`/`cast_model(cast_t=)` → `request_type`/`target_type`, `load_model(refer=)` → `target=`.
30. `binded_cb` → `generate_cb`(bind의 과거분사는 bound), `shared_sender` → `router`(실제로는
    `SendRouter`), `id` → `stage_id`(내장 함수를 가림), 이름 없는 내부 함수 `_` → `_pump`.
31. `transq_dict`/`seq_sender_dict`/`active_stage_set` → `slot_channels`/`slot_senders`/`upstream_stages`,
    `tt`/`ss`/`sss`/`act`/`reg` 같은 한두 글자 변수에 뜻 있는 이름을 붙인다.
32. `Domain._tmg` → `_tasks`, `_count`/`_generate_id` → `_stage_seq`/`_next_stage_id`(`generate_id`와
    이름이 비슷한데 하는 일이 다르다), `_gen_req` → `_stream_impl`.
33. 쓰지 않는 코드 삭제: `InitGenWrap`/`InitDependWrap`/`InitReqWrap`, `Domain._close_stage`,
    `model.py`의 주석 처리된 옛 코드.

### 그대로 두기를 추천

- `Domain`: 이름과 위치(`trading_core.Domain`) 모두
- `start`/`wait`/`stop`, `Subscription`의 `update`/`detach`
- `Sender`/`Receiver`, `@x.detached`/`@x.unbind`, `DataModel`, `initialize`
- `Tr` 접두사(`TrBaseModel`, `_tr_*`)와 어노테이션 키 `tr_annotation`: pydantic 사용자 필드와 이름이
  부딪히지 않게 하는 네임스페이스다
- `logger.py`의 이름들, 타입 매개변수 `Tctx`/`Treq`/`Tin`/`Tout`

## 4. 적용 순서

A~C절은 공개 계약과 직렬화 형식이라 먼저 확정한다. D~G절은 내부 이름이라 나중에 해도 된다.
한 번에 한 절씩 적용하고, 절마다 검증을 통과시킨다.

## 5. 적용 절차

- 공개 이름(`__init__.__all__`)을 바꾸면 함께 고친다: `examples/*`와 각 README, `tests/*`,
  `AGENTS.md`(아키텍처·테스트 표·저장소 메모), `docs/TODO.md`.
- 찾기: `grep -rn '<옛이름>' src tests examples docs AGENTS.md README.md`. 문자열 리터럴(`"instanter"`,
  `"__require__"`)과 예외 메시지·docstring 안의 이름도 빠뜨리지 않는다.
- 8번은 이름만 바꾸는 게 아니라 반환값도 바뀐다. ex03·ex08과 `tests/test_domain.py`의 사용처를 함께
  고친다.

## 6. 검증

- `uv run ruff check .` / `uv run ruff format --check .` / `uv run pyright` / `uv run pytest`
- `uv run examples/main.py serial`
- 옛 이름을 `grep`해서 0건인지 확인한다.

## 7. 적용하며 달라진 점

- **12번 예외 이름**: 계획은 `ModelLoadError`였지만 `ModelValidationError`로 했다. `cast_model()`도
  같은 예외를 던지는데, 캐스트는 "로드"가 아니다. 둘 다 "검증 실패"라 이 이름이 둘을 함께 덮는다.
- **17번 생성 메서드**: 구독 핸들이 `Subscription`이 되었으므로 `_create_source/derived/session_stage`
  대신 `_create_source/derived/session_subscription`으로 했다. 분기하는 `_define_stage`는
  `_create_subscription`이다.
- **5·7번 속성**: `Subscription`은 `request`·`sender`를, `SharedStage`는 `request`·`router`를 가진다.
  공통 부분(`id`·`request`)만 `BaseStage`에 남겼다.
- **8번**: `get_shared_symbols()`를 쓰도록 ex03·ex08과 `tests/test_domain.py`를 고쳤다. 스테이지
  동일성(`is`)으로 공유를 확인하던 테스트는 심볼 합집합과 init 횟수로 확인한다. ex08의
  `report_registry()`는 `report_sharing()`이 되었다.
- **15번 센티널**: `"__always__"`를 모듈 상수 `_ALWAYS_SLOT`으로 두었다.
- **함께 바꾼 것**: `BindPack`의 `set/get_generate_cb` → `set/get_source_cb`, `set/get_dependent_cb` →
  `set/get_derived_cb`, `set/get_require_cb` → `set/get_always_cb`. 세 번 반복되던 "detach 뒤 호출을
  막는" 코드는 `_mark_detached()` 하나로 모았다. 세션 슬롯을 여는 반복 코드는 `open_slot()`으로 모았다.
- **테스트 파일**: `test_helper.py`는 `test_ids.py`와 `test_tasks.py`로, `test_transport.py`는
  `test_routing.py`로 나누거나 이름을 바꿨다. `test_instant_*` 테스트는 `test_session_*`이 되었다.
- **로거 이름**: `TaskManager` 로그는 `trading_core.tasks`, 라우터 경고는 `trading_core.routing`에서
  나온다.
- **직렬화 호환**: 모델 타입 리터럴과 `tr_annotation` 키(`id` → `uid`, `generated_origin` →
  `created_by`)가 바뀌어 옛 덤프는 `load_model()`로 되살릴 수 없다. 아직 배포 전이라 호환 경로는 두지
  않았다.
- **20번을 적용하며 드러난 캐시 결함**: `Domain`이 캐시된 `tr_content_id`를 쓰게 되면서, 원래 있던 캐시의
  두 결함이 실제 동작에 닿게 되었다. (1) 캐시를 `object.__setattr__`로 써서 private 저장소가 아니라
  필드(`__dict__`)에 들어갔다. (2) `model_copy(update=...)`가 원본의 캐시를 그대로 들고 와 복사본이
  원본의 content_id를 냈다 — `Domain`이라면 복사본을 원본의 공유 스테이지에 붙인다. 캐시를 pydantic의
  `__setattr__`로 쓰고 `model_copy()`에서 비우도록 고쳤다(`tests/test_model.py`의
  `test_content_id_cache_is_not_carried_into_an_updated_copy`, `test_content_id_cache_is_not_a_field`).
- **8번이 약하게 만든 검증**: `get_shared_symbols()`는 "공유 안 됨"과 "공유되지만 심볼 없음"이 둘 다 빈
  집합이다. 그래서 `test_equal_session_requests_do_not_share_a_stage`는 세션 요청이 공유 레지스트리에
  들어가지 않는지를 `domain._shared_stages`로 직접 본다.
