# ex07: `RequestModel`로 심볼마다 시퀀스 붙이기

ex01~ex06의 요청은 모두 "심볼 집합 하나 → generator 하나"였다. `GenerateModel`이든
`DependentModel`이든, binder는 심볼 **집합**을 통째로 받아 하나의 async generator를
돌렸다.

`RequestModel`은 다르다. **심볼마다 슬롯 하나**를 만들고, 각 슬롯이 `Sequence`로 상위
원천에 붙는다. 등록되면 모델 타입이 `"instanter"`가 된다.

이 예제가 보여 주는 것은 이 한 문장이다.

> 소비자가 구독하는 심볼과 원천이 아는 심볼은 달라도 된다. 그 변환을 시퀀스가 맡는다.

## 상위 표기와 하위 표기

instanter를 이해하려면 두 심볼을 구분해야 한다. 이름이 헷갈리면 나머지가 다 헷갈린다.

| | 무엇인가 | ex07에서 | 어디서 나오나 |
| --- | --- | --- | --- |
| **하위 표기** | 소비자가 구독한 심볼 | `"BTC"` | bind 콜백이 받는 `symbol` 인자 |
| **상위 표기** | 원천 generator가 아는 심볼 | `"BTC/USD"` | `req(symbol)`에 넘기는 값 |

```python
@swing
async def _(ctx: SwingCtx, symbol: str):          # symbol = "BTC"  (하위)
    yield TickReq()(f"{symbol}/{ctx.quote}") | SwingRunnable(ctx.quote, symbol)
    #             ^^^^^^^^^^^^^^^^^^^^^^^^^ "BTC/USD"  (상위)
```

원천에 올라가는 심볼은 `{"BTC/USD", "ETH/USD", "XRP/USD"}`이고, 소비자가 받는 데이터의
`symbol`은 다시 `"BTC"`다. 되돌리는 일은 `SwingRunnable`이 한다.

## 파일 구성

- `ex07.py`: 원천(`TickReq`)과 요청형(`SwingReq`) 한 쌍, 그리고 그 사이를 잇는
  `SwingRunnable`.
- `run_ex.py`: `Domain.request()`로 스윙 6건을 받고 끝낸다.

## 예제의 흐름

1. `TickReq`는 필드가 없는 원천이다. 상위 표기로 현재가를 0.5초마다 1씩 올려 발행한다.
2. `SwingReq(quote="USD")`를 `{"BTC", "ETH", "XRP"}`로 구독한다.
3. 심볼마다 bind 콜백이 한 번씩 불려 시퀀스를 하나씩 만든다. 세 슬롯이 생긴다.
4. 각 시퀀스는 `TickReq()("BTC/USD")`로 상위를 구독하고 `| SwingRunnable("USD", "BTC")`로
   변동폭 계산 단계를 잇는다.
5. `Domain`은 세 시퀀스가 요구한 상위 표기의 합집합을 `TickReq` 원천에 등록한다.
6. 원천 데이터는 상위 표기로 라우팅되어 해당 슬롯으로 들어가고, `SwingRunnable`이
   하위 표기의 `SwingData`로 바꿔 소비자에게 보낸다.

## 실행

```bash
uv run python examples/ex07/run_ex.py
```

```text
symbol=BTC quote=USD price=101.0 swing=1.0
symbol=ETH quote=USD price=201.0 swing=1.0
symbol=XRP quote=USD price=301.0 swing=1.0
symbol=BTC quote=USD price=102.0 swing=1.0
symbol=ETH quote=USD price=202.0 swing=1.0
symbol=XRP quote=USD price=302.0 swing=1.0
```

(위는 `tr_annotation`을 뺀 요약이다. 실제로는 각 건이 `model_dump_json(indent=2)`으로
출력된다.)

## 관전 포인트

**`symbol`이 `"BTC"`다.** 원천은 `"BTC/USD"`로 발행했는데 소비자는 `"BTC"`로 받는다.
`SwingRunnable.invoke()`가 `SwingData(symbol=self.symbol, ...)`로 하위 표기를 다시 붙이기
때문이다. 이걸 빠뜨리면 데이터가 상위 표기인 채로 나가고, `"BTC"`를 구독한 소비자에게는
아무것도 가지 않는다 — 오류 없이 조용히 사라진다(ex04의 "역변환을 빠뜨리면" 항목과 같은
함정이다).

**첫 틱이 안 보인다.** 가격은 `100`부터 시작하는데 첫 출력은 `101.0`이다.
`SwingRunnable.invoke()`가 첫 호출에서 기준가만 잡고 `None`을 돌려주기 때문이다.
시퀀스 단계가 `None`을 반환하면 그 데이터는 소비자에게 가지 않는다. 비교할 직전 값이
없는 첫 데이터를 걸러내는 흔한 방법이다.

**`Runnable`이 상태를 갖는다.** `SwingRunnable.active_price`는 직전 가격을 기억한다.
심볼마다 **별개의 인스턴스**가 만들어지므로(bind 콜백이 심볼마다 한 번씩 불린다) 서로
간섭하지 않는다. 슬롯이 심볼 단위라는 점이 여기서 드러난다.

**`swing`이 계속 `1.0`이다.** 원천이 매번 1씩 올리는 모의 가격이라 그렇다. 변동폭 계산이
직전 값과의 차이라는 것만 확인하면 된다.

## 알아둘 점

- `quote`는 `SwingReq`의 필드이므로 `content_id`에 포함된다. `quote="USD"`와
  `quote="KRW"`는 **서로 다른 스테이지**이고, 상위 `TickReq`는 필드가 없어 둘이 하나를
  공유한다. `INIT_PRICE_DICT`에 KRW 가격이 함께 있는 이유다.
- `bind` 콜백은 심볼이 **새로 구독될 때** 한 번 불린다. 심볼 집합이 바뀌어도 이미 있던
  슬롯은 다시 만들지 않는다. 원천·파생 스테이지처럼 generator를 통째로 재시작하는 일이
  없다.
- 짝이 되는 정리 콜백은 `@x.unbind`(심볼 하나가 빠질 때)와 `@x.detached`(스테이지 전체).
  이 예제는 둘 다 쓰지 않지만, 실제 어댑터라면 `unbind`에서 그 심볼의 구독 해제 메시지를
  보내게 된다. 슬롯이 `update()`로 빠지든 스테이지가 닫히든 `unbind`는 심볼당 한 번이다.
- `require`를 쓰면 구독 심볼과 무관하게 늘 붙는 시퀀스를 하나 더 둘 수 있다(하트비트
  채널 같은 것). 이 예제는 쓰지 않는다.

## 어디를 검증하는가

`domain.py`의 `_define_inst_stage()`다. 특히 상위 스테이지에 등록할 심볼을 고르는 곳이
이 예제의 핵심이다.

```python
updating.append((req_stage, reg.router.symbols))
#                            ^^^^^^^^^^^^^^^^^^ 시퀀스가 요구한 상위 표기
```

여기에 이 스테이지가 받은 하위 심볼을 넣으면 원천이 `"BTC"`를 구독하게 되어
`current_price_dict["BTC"]`에서 `KeyError`가 난다. 상·하위 표기가 같은 요청으로만
시험하면 이 실수가 드러나지 않는다. 같은 시나리오를 테스트로 굳힌 것이
`tests/test_domain.py`의 `test_instant_stage_maps_symbols_to_the_upstream`이다.
