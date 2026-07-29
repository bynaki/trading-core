# ex03: `Domain.stage()`로 구독 심볼 직접 갱신하기

이 예제는 `Domain.request()`보다 낮은 수준의 API인 `Domain.stage()`를 사용한다.
호출자가 출력 `Sender`를 직접 제공하고, 스테이지가 열린 동안 `update()`를 여러 번
호출하여 구독 심볼을 동적으로 추가하거나 제거한다.

## 파일 구성

- `ex03.py`: 가격 요청·데이터 모델, 상태를 유지하는 컨텍스트와 제너레이터를 정의한다.
- `run_ex.py`: 두 스테이지가 같은 원천을 공유하며 심볼 합집합을 바꾸는 과정을 실행한다.

## 가격 컨텍스트

`PriceReq.ohlc` 값은 가격 증가 단위를 결정한다.

| `ohlc` | 증가 단위 |
| --- | ---: |
| `open` | 10 |
| `high` | 1,000 |
| `low` | 1 |
| `close` | 100 |

`PriceContext`는 심볼별 발행 횟수를 보관한다. 예를 들어 `close` 요청에서 같은 심볼이
세 번 선택되면 가격은 100, 200, 300 순서로 증가한다. 심볼 합집합 변경으로 binder가
재시작되어도 동일한 원천 컨텍스트를 사용하므로 누적 횟수는 유지된다.

## `Domain.stage()` 사용 흐름

```python
sender = TestSender()
req = PriceReq(ohlc="close")

async with domain.stage(req, sender) as stage:
    await stage.update({"BTC"})
    await stage.update({"BTC", "ETH"})
    await stage.update({"ETH"})
```

`stage()`에는 다음 두 요소를 직접 전달한다.

- 요청 모델: 어떤 원천 제너레이터를 사용할지와 원천 스테이지의 `content_id`를 정한다.
- `Sender`: 해당 스테이지가 구독한 심볼의 `PriceData`를 받을 비동기 호출 객체다.

`update()`는 이전 심볼 집합을 교체한다. 같은 요청을 사용하는 모든 스테이지의 심볼
합집합이 실제 원천 binder의 입력이 되며, 합집합이 달라질 때만 기존 binder를 정리하고
새 집합으로 다시 시작한다.

## 공유 원천 확인

`run_ex.py`는 동일한 `PriceReq(ohlc="close")`를 사용하는 두 스테이지를 동시에 연다.
요청 내용이 같으므로 두 스테이지는 같은 `content_id`와 하나의 원천 스테이지를 공유한다.

각 실행 루프는 자신의 심볼을 단계적으로 추가·제거하고 다음 값을 비교한다.

- 현재 개별 스테이지가 요청한 `symbols`
- `domain.get_origin_stage(content_id).output.symbols`에 저장된 전체 합집합

개별 심볼 집합이 원천 합집합에 포함된다는 assertion으로 공유 상태를 확인한다.
`SharedSender`는 원천에서 무작위로 선택된 심볼의 데이터를 그 심볼을 구독한 sender에만
전달한다.

## 정리 시점

- binder의 `finally`는 심볼 합집합이 바뀌어 업데이트가 재시작될 때마다 실행된다.
- `@price.close`는 마지막 스테이지가 닫혀 전체 심볼 합집합이 비었을 때 실행된다.
- `async with domain.stage(...)`를 벗어나면 해당 sender의 구독은 자동으로 제거된다.

빈 합집합에서는 binder를 실행하지 않으므로 `random.choice()`에 빈 시퀀스가 전달되지
않는다. 예제 binder 자체는 무한 스트림이므로 반드시 스테이지 컨텍스트나 `Domain`을
정상적으로 종료해야 한다.

## 실행

프로젝트 루트에서 다음 명령을 실행한다.

```bash
uv run python examples/ex03/run_ex.py
```
