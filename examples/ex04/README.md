# ex04: `require`로 상위 요청과 심볼을 함께 변환하기

이 예제는 심볼 표기와 필드 이름이 서로 다른 두 거래소를 하나의 요청·하나의 출력
모델로 정규화한다. ex02가 "어떤 원천이 필요한가"만 선언했다면, ex04는 **심볼 집합까지
변환하는 require 콜백**과 **요청 값에 따라 달라지는 상위 원천**을 보여준다.

소비자는 `"BTC"`, `"ETH"` 같은 기초 자산만 요청한다. 어느 거래소의 어떤 표기로
구독할지는 `OHLCRequest.quote`가 결정한다.

## 파일 구성

- `ex04.py`: 두 거래소 원천(USD · KRW)과 이를 정규화하는 파생 요청을 정의한다.
- `run_ex.py`: 견적 통화만 바꿔 같은 심볼을 두 번 구독하는 실행 예제다.

## 두 개의 가짜 거래소

| | USD 마켓 | KRW 마켓 |
| --- | --- | --- |
| 요청 | `BinanceRequest` | `UpbitRequest` |
| 지원 주기 | `1m` · `5m` · `1h` | `5m` · `30m` · `1h` |
| 출력 모델 | `BinanceData` (`op`/`hi`/`lo`/`cl`/`vol`) | `OHLCData` (`open`/`high`/…) |
| 심볼 표기 | `BTC/USD` · `ETH/USD` | `BTC/KRW` · `ETH/KRW` |

두 원천 모두 주기별로 10개의 모의 캔들을 0.5초 간격으로 순환 발행한다. 정의되지 않은
심볼을 받으면 예외를 던져 잘못된 구독을 즉시 드러낸다.

`OHLCRequest.interval`은 두 거래소가 공통으로 지원하는 `5m` · `1h`로 제한된다.
한쪽만 지원하는 주기는 파생 요청에서 아예 표현할 수 없다.

## 심볼까지 변환하는 require

`DependentModel.require`는 두 가지 형태의 콜백을 받는다. 위치 인자 개수로 구분하며,
요청만 받는 형태는 심볼을 그대로 흘려보내는 래퍼로 감싸진다.

```python
# ex02: 상위 요청만 만든다. 심볼은 그대로 전달된다.
@NamingReq.require
def naming_requirement(req: NamingReq) -> origin.NamingAllReq:
    return origin.NamingAllReq()


# ex04: 상위 요청과 상위 심볼 집합을 함께 만든다.
@OHLCRequest.require
def ohlc_requirement(req: OHLCRequest, symbols: set[str]):
    if req.quote == "usd":
        return BinanceRequest(interval=req.interval), {f"{s}/USD" for s in symbols}
    elif req.quote == "krw":
        return UpbitRequest(interval=req.interval), {f"{s}/KRW" for s in symbols}
```

`Domain`은 파생 스테이지를 갱신할 때마다 `get_tr_require_with_symbol(symbols)`로 이
콜백을 호출하고, 반환된 요청으로 상위 원천 스테이지를 만들거나 재사용한 뒤 반환된
심볼 집합으로 구독한다. 즉 **상위 요청과 상위 심볼이 같은 콜백에서 함께 결정된다.**

`quote`에 따라 반환하는 요청 타입 자체가 달라지므로, 하나의 파생 요청이 두 원천 중
하나로 라우팅된다. 소비자 쪽 코드는 바뀌지 않는다.

## 데이터 흐름

```text
OHLCRequest(quote="usd", interval="5m") + {"BTC", "ETH"}
    -> require -> BinanceRequest(interval="5m") + {"BTC/USD", "ETH/USD"}
    -> BinanceData(op, hi, lo, cl, vol, symbol="BTC/USD")
    -> Receiver
    -> OHLCData(open, high, low, close, volume, symbol="BTC")
```

```text
OHLCRequest(quote="krw", interval="1h") + {"BTC", "ETH"}
    -> require -> UpbitRequest(interval="1h") + {"BTC/KRW", "ETH/KRW"}
    -> OHLCData(..., symbol="BTC/KRW")
    -> Receiver
    -> OHLCData(..., symbol="BTC")
```

USD 경로는 줄임말 필드를 정규 필드로 옮겨 담고, KRW 경로는 필드 이름이 이미 같으므로
`model_copy(update={"symbol": ...})`로 심볼만 바꾼다. 두 경로 모두 `cast_model()`로
수신 데이터를 좁히는데, `cast_model()`은 상속이 아니라 `model_id` 정확 일치를 요구한다.

## 두 개의 심볼 공간

이 예제에는 심볼 공간이 두 개 있다.

- **하위(소비자) 공간**: `BTC`, `ETH`
- **상위(거래소) 공간**: `BTC/USD`, `BTC/KRW`

require 콜백이 하위 → 상위 변환을, binder의 `base_of()`가 상위 → 하위 역변환을
담당한다. **역변환을 빠뜨리면 데이터가 사라진다.** `SharedSender`는 발행된 데이터의
`symbol`로 구독자를 찾으므로, `"BTC/USD"`인 채로 내보내면 `{"BTC"}`를 구독한
소비자에게 전달되지 않는다.

binder가 받은 데이터의 심볼이 현재 구독 심볼 집합에 없으면 예외 대신 경고만 출력하고
건너뛴다. 변환이 어긋난 상황을 스트림을 끊지 않고 드러내기 위한 방어 코드다.

## `content_id`와 스테이지 공유

- `quote`와 `interval`은 모두 요청 내용에 포함되므로 `content_id`에 반영된다.
  `OHLCRequest(quote="usd", interval="5m")`과 `OHLCRequest(quote="krw", interval="1h")`은
  서로 다른 파생 스테이지를 쓰고, 결과적으로 상위 원천도 달라진다.
- 반대로 같은 `quote`·`interval` 요청은 파생 스테이지와 상위 원천을 공유한다.
- `run_ex.py`는 앞 요청의 구독을 모두 정리한 뒤 다음 요청을 시작한다. 따라서 실행
  로그에서 원천 태스크가 하나씩만 살아 있는 것을 확인할 수 있다.

## 알아둘 점

- 원천 binder는 무한히 발행하므로 소비자가 개수를 세어 `break`해야 한다. `async with`를
  빠져나오면 구독이 정리되고, 마지막 구독이 사라지면 상위 원천 스테이지까지 함께
  닫힌다(로그의 `[TASK CANCELLED]` 두 줄).
- 모의 데이터는 주기마다 10개뿐이라 계속 소비하면 같은 캔들이 반복된다.
- 상위 원천에 등록되는 심볼은 파생 스테이지 구독자 **전체의 합집합**을 변환한 결과다.
  따라서 같은 파생 요청을 서로 다른 심볼 집합으로 동시에 구독해도 서로를 밀어내지
  않는다. 이 동작을 고정한 예제가 ex05다.
- 다만 require 콜백이 **심볼에 따라 다른 상위 요청**을 반환하면 안 된다. 파생 스테이지는
  상위 하나만 바라보기 때문이다. 이 예제처럼 요청 필드(`quote`)로 상위가 갈리는 것은
  `content_id`가 달라 파생 스테이지 자체가 분리되므로 문제가 없다.
- 이 예제는 `@ohlc.detached` 정리 콜백을 두지 않는다. 컨텍스트가 요청 모델 자체라
  분리할 외부 자원이 없기 때문이다. 컨텍스트 정리가 필요한 형태는 ex02를 참고한다.

## 실행

프로젝트 루트에서 다음 명령을 실행한다.

```bash
uv run python examples/ex04/run_ex.py
```
