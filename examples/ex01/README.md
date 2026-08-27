# ex01: `Domain.request()`로 데이터 스트림 구독하기

이 예제는 요청 모델과 심볼 집합을 `Domain.request()`에 전달하고, 반환된 비동기
스트림을 소비하는 가장 단순한 사용법을 보여준다. 스트림 소비를 중단했을 때
제너레이터와 스테이지의 정리 콜백이 어떤 순서로 실행되는지도 확인할 수 있다.

## 파일 구성

- `ex01.py`: 요청·데이터 모델과 원천 제너레이터를 정의한다.
- `run_ex.py`: `Domain`을 시작하고 스트림에서 데이터를 읽는 실행 예제다.

## 예제의 흐름

1. `CountReq(start=1)`이 카운트를 시작할 값을 정한다.
2. `@initialize`가 init 콜백의 첫 인자 어노테이션(`req: CountReq`)에서 요청 타입을
   추론해 `CountReq`의 binder를 등록한다.
3. `gen01()`은 요청 모델 자체를 스테이지 실행 컨텍스트로 사용한다.
4. `@gen01`이 붙은 generate 콜백이 구독 심볼을 순환하며 `CountData`를 계속 발행한다.
5. `run_ex()`는 `count == 10`일 때 스트림 소비를 중단한다.
6. 요청 컨텍스트를 벗어나면 현재 업데이트가 취소되고, 마지막 구독자가 사라지면서
   스테이지 종료 콜백까지 실행된다.

핵심 코드는 다음과 같다.

```python
req = CountReq(start=1)
symbols = {"BTC", "USDT", "ETH", "XRP"}

async with domain.request(req, symbols) as stream:
    async for data in stream:
        print(data.model_dump_json(indent=2))
        if data.count == 10:
            break
```

`Domain.request()`는 내부적으로 출력 큐와 `Stage`를 만들고, 전달받은 심볼을
`Stage.update()`에 등록한다. 사용자는 이 세부 과정을 다루지 않고 비동기 반복자로
결과만 받을 수 있다.

## 두 가지 정리 시점

이 예제는 서로 다른 범위의 정리 지점을 구분한다.

- generate 콜백의 `finally`: 심볼 구성이 바뀌어 현재 업데이트가 재시작되거나 요청
  소비가 중단될 때 실행된다. 업데이트 단위의 네트워크 연결·구독 같은 자원을
  정리하기 적합하다.
- `@gen01.detached`: 해당 요청의 마지막 구독자가 사라져 원천 스테이지가 제거될 때
  한 번 실행된다. 스테이지 컨텍스트 전체가 소유한 자원을 정리하기 적합하다.

따라서 `async for`에서 `break`하더라도 `async with`를 빠져나오면 정리 절차가
이어진다. `Domain` 자체는 실행이 끝난 뒤 `stop()`으로 종료해야 한다.

## 알아둘 점

- generate 콜백은 `while True`로 무한히 발행하므로 스스로 끝나지 않는다. 소비자가
  `break`하거나 태스크가 취소되어야 종료된다. `start` 값은 시작 숫자만 정할 뿐
  종료 조건이 아니다.
- 심볼은 `set`으로 전달되므로 최초 순서는 보장되지 않는다. 다만 실행 중 만들어진
  심볼 목록 안에서는 카운트가 증가할 때마다 순환한다.
- 빈 심볼 집합은 아예 generator를 시작시키지 않는다. `Domain`은 심볼 합집합이 비면
  스테이지를 만들지 않고 정리한다.

## 실행

프로젝트 루트에서 다음 명령을 실행한다.

```bash
uv run python examples/ex01/run_ex.py
```
