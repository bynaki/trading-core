# 예제

`trading-core`의 기능과 사건을 **예제 하나에 하나씩** 보인다. 예제는 모두 파일 하나로 끝나고,
위에서 아래로 읽으면 된다. 무엇을 배우는지와 기대 출력은 각 파일 맨 위의 docstring에 있다.
처음이라면 ex01부터 차례로 보자. 각 docstring 끝의 "다음"이 다음 예제를 가리킨다.

## 실행

```bash
uv run examples/ex01_stream.py     # 파일을 직접 실행 (예제가 자기 Domain을 만든다)
uv run examples/main.py ex01       # 번호로 실행
uv run examples/main.py serial     # 전부를 Domain 하나에서 차례로
uv run examples/main.py parallel   # 전부를 Domain 하나에서 동시에
```

예제마다 핵심 지점에 `assert`가 있다. `serial`·`parallel`이 끝까지 돌면 예제가 보이는 동작이 지금
코드에서도 그대로라는 뜻이다.

## 목차

**1부 — 소스 요청의 기본**

| # | 파일 | 배우는 것 |
| --- | --- | --- |
| 01 | `ex01_stream.py` | 가장 작은 소스 요청, `Domain.stream()`, start/stop |
| 02 | `ex02_subscribe.py` | `subscribe()`와 Sender, `update()`는 교체, 빈 집합은 해제 |
| 03 | `ex03_cleanup.py` | 두 정리 지점: generator의 `finally`와 `@detached` |
| 04 | `ex04_sharing.py` | 내용(content_id)이 같은 요청은 스테이지 하나를 나눠 쓴다 |
| 05 | `ex05_union.py` | binder는 심볼 합집합을 받고, 데이터는 구독한 소비자에게만 간다 |
| 06 | `ex06_restart.py` | 합집합이 바뀔 때만 재시작, 컨텍스트는 재시작을 넘어 남는다 |

**2부 — 파생 요청**

| # | 파일 | 배우는 것 |
| --- | --- | --- |
| 07 | `ex07_derived.py` | `require`로 상위 요청 정하기, `recv()`, 여러 파생이 소스 스테이지 하나를 공유 |
| 08 | `ex08_mapped_symbols.py` | 심볼까지 바꾸는 `require`, 되돌리지 않으면 데이터가 조용히 사라진다 |
| 09 | `ex09_choose_upstream.py` | 요청 필드로 상위 소스 요청 고르기(심볼별로는 못 고른다) |
| 10 | `ex10_chained.py` | 파생 위의 파생, 정리는 아래에서 위로 |

**3부 — 세션 요청**

| # | 파일 | 배우는 것 |
| --- | --- | --- |
| 11 | `ex11_session.py` | 심볼마다 슬롯 하나, bind → `Pipeline`, `Runnable`, 상·하위 표기 |
| 12 | `ex12_unbind.py` | `@x.unbind`와 `@x.detached`, bind와 unbind는 한 번씩 짝 |
| 13 | `ex13_not_shared.py` | 내용이 같아도 세션 요청은 나눠 쓰지 않는다 |
| 14 | `ex14_multi_step.py` | 단계가 여럿인 파이프라인, `None`이면 거기서 멈춘다 |
| 15 | `ex15_two_sources.py` | bind가 파이프라인 여럿을 yield해 한 슬롯이 상위 둘에 붙는다 |
| 16 | `ex16_always.py` | 구독 심볼과 상관없이 늘 붙는 `@x.always` |

**4부 — 실패**

| # | 파일 | 배우는 것 |
| --- | --- | --- |
| 17 | `ex17_source_failure.py` | 소스 generator가 던지면 재시도 없이 `StageFailed`, 파생까지 연쇄, 다시 넣기 |
| 18 | `ex18_sender_failure.py` | 소비자 하나가 던지면 그 소비자만 떼어 낸다 |
| 19 | `ex19_cleanup_failure.py` | 정리 콜백이 던져도 정리는 끝까지 한다 |
| 20 | `ex20_stream_failure.py` | `stream()`은 실패하면 `StageFailed`를 던진다 |
| 21 | `ex21_init_failure.py` | init이 던지면 스테이지를 세우지 않고 알린다 |
| 22 | `ex22_session_failure.py` | 세션의 init·bind·파이프라인 단계가 던질 때, 그 심볼만 실패 |
| 23 | `ex23_always_failure.py` | always가 실패하면 세션 전체가 실패하고 init부터 다시 |
| 24 | `ex24_symbol_rejected.py` | `SymbolRejected`로 심볼 하나만 거부하기 |

**5부 — 더 알아둘 것**

| # | 파일 | 배우는 것 |
| --- | --- | --- |
| 25 | `ex25_slow_consumer.py` | 느린 소비자가 공유 generator를 붙잡는다, 자기 큐로 떼어 내기 |
| 26 | `ex26_mistakes.py` | 등록·사용 실수: `BindError`·`DomainError`·`ModelError` |
| 27 | `ex27_identifiers.py` | uid·model_id·content_id, 가변 모델, 구독은 요청의 사본 |
| 28 | `ex28_serialization.py` | `tr_annotation`, `load_model`·`parse_dump`·`cast_model`, 인스턴스 ID |
| 29 | `ex29_logging.py` | 로그 모듈: 싱크별 레벨, 발신처, 예외 레코드 |
| 30 | `ex30_data_types.py` | 요청 하나가 데이터 여러 종류를 줄 때 `match`로 가르기 |

## 예제의 생김새

모든 예제가 같은 틀을 따른다.

1. 모듈 docstring — 배우는 것, 실행, 기대 출력, 다음 예제
2. `# ===== binder 쪽 =====` — 요청·데이터 모델과 binder(거래소 쪽을 흉내 낸 코드)
3. `# ===== 소비자 쪽 =====` — `run_ex(domain)`: 구독하고, 로그를 남기고, `assert`로 확인한다
4. `main()` — 로그를 구성하고 `Domain`을 띄워 `run_ex()`를 부른 뒤 꼭 `stop()`한다

`main.py`는 `examples/exNN_이름.py` 파일을 찾아 `run_ex(domain)`을 부른다. 예제를 새로 넣을 때 이
틀을 따르면 `main.py`를 고칠 필요가 없다.

## 출력 읽기

- 출력은 `print`가 아니라 `trading_core.logger`의 로그다. 줄마다 붙는 로거 이름(`ex05`, `ex05.tick`
  등)으로 어느 예제의 어느 부분이 남긴 줄인지 가린다. `parallel`로 줄이 섞여도 이 이름으로 본다.
- 공용 로그 설정은 `setting.toml`이다. ex29만 자기 설정(`ex29_logging.toml`)으로 바꿨다가 끝에
  공용 설정으로 되돌린다.
- 4부(17~24)에서 `trading_core.domain`이 남기는 ERROR 줄과 트레이스백은 고장이 아니라 예제가 일부러
  낸 실패의 기록이다.
- docstring의 기대 출력은 줄 앞의 레벨을 뺐고, 트레이스백 같은 긴 줄은 줄였다. 실행마다 건수나
  순서가 조금 다른 곳은 docstring에 적어 두었다.
