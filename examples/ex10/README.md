# ex10: 콜백이 던질 때의 처리

ex01~ex09는 모든 콜백이 잘 도는 경우만 다뤘다. ex10은 binder의 generator, 소비자 `Sender`,
정리 콜백이 **예외를 던질 때** 코어가 무엇을 하는지 보여 준다.

정책을 한 문장으로 줄이면 이렇다.

> 코어는 재시도하지 않는다. 실패한 스테이지를 내리고, 영향받은 소비자에게 **자기 심볼만**
> 담은 `StageFailed`를 `on_error`로 알린다. 정리 실패는 로그로만 남긴다.

재시도는 binder 몫이다. 무해한 끊김을 버틸지(재연결 등)는 binder가 generator 안에서 정한다.
코어까지 다시 시도하면 요청이 여러 단계를 거칠 때 재시도가 단계마다 곱해진다.

## 파일 구성

- `ex10.py`: 실패를 주입할 수 있는 원천(`TickReq`) · 파생(`PriceReq`) 한 쌍.
  - `TRIPPED`에 요청의 `tag`가 들면 원천 generator가 다음 발행 직전에
    `ConnectionError("거래소 연결이 끊겼다")`를 던진다(한 번만).
  - `fail_on_detach=True`인 요청은 `detach` 콜백이 던진다.
  - init · generator 시작 · detach 횟수를 `tag`별로 `INITS`·`GEN_STARTS`·`DETACHES`에 센다.
    `run_ex()`가 시작할 때 `reset()`으로 비워, 한 프로세스에서 다시 돌려도 판정이 맞는다.
- `run_ex.py`: 네 시나리오를 돌리고 끝에 판정을 남긴다. 시나리오마다 `tag`가 달라
  content_id가 달라지므로 스테이지가 따로 선다.

## 받는 쪽: `on_error`와 `StageFailed`

```python
async def on_error(failed: StageFailed) -> None:
    failed.symbols     # 이 소비자가 잃은 심볼만 (frozenset)
    failed.cause       # "ConnectionError: 거래소 연결이 끊겼다" — 문자열이라 직렬화할 수 있다
    failed.__cause__   # 같은 프로세스 안에서는 원래 예외(연쇄면 상위의 StageFailed)

async with domain.subscribe(req, sender, on_error) as sub:
    await sub.update({"BTC/USD"})
```

- `on_error`를 안 주면 코어가 ERROR 로그만 남긴다.
- 원천·파생의 실패는 코어가 띄운 태스크에서 `on_error`로 온다. 세션의 init·bind·always 콜백
  실패만은 `update()`가 돌아오기 전에 그 자리에서 알린다. 어느 쪽이든 `update()`·`subscribe()`는
  실패를 던지지 않는다.
- 실패한 심볼은 구독에서 빠진다. 구독 객체 자체는 살아 있어 `sub.update()`로 다시 넣을 수 있다.

## 시나리오

| # | 무엇이 던지나 | 코어가 하는 일 | 소비자가 보는 것 |
| --- | --- | --- | --- |
| 1 | 원천 generator | 재시도 없이 원천 스테이지를 내리고, 그 원천을 상위로 둔 파생 스테이지까지 연쇄로 내린다. 둘 다 `detach` | 원천 소비자 A·파생 소비자 B 모두 `on_error`. 각자 자기 심볼만 |
| 2 | 소비자 `Sender` D | D만 라우터에서 뗀다. 공유 generator는 그대로 | D만 `on_error`. 같은 스트림의 C는 계속 받는다 |
| 3 | `detach` 콜백 | 정리를 끝까지 하고 ERROR 로그 | 아무것도 — `async with`가 예외 없이 끝난다 |
| 4 | 원천 generator (`stream()`으로 소비) | 1과 같다 | `async for`에서 `StageFailed`가 던져진다 |

1번에서는 이어서 A가 실패한 심볼을 `sub_a.update()`로 다시 넣는다. 그러면 **새 스테이지가
init부터** 선다(`init 2회차`). 재시도가 아니라 소비자가 고른 재구독이다.

## 실행

```bash
uv run python examples/ex10/run_ex.py
uv run examples/main.py ex10
```

```text
ex10: ----- 1. 원천 generator가 던진다 -----
ex10.origin: init 1회차 {tag=ex10.source}
ex10.origin: generator 1회차 시작 {tag=ex10.source, upper=['BTC/USD', 'ETH/USD']}
ex10.derived: generator 시작 {tag=ex10.source, lower=['BTC']}
ex10: 수신 B {symbol=BTC}
ex10: 수신 A {symbol=ETH/USD}
...
ex10.origin: generator 정리 {tag=ex10.source}
ex10.origin: detach {tag=ex10.source}
trading_core.domain: 스테이지가 실패했다 {stage=TickReq@ex10:...:2, symbols=['BTC/USD', 'ETH/USD']}
Traceback (most recent call last):
  ...
ConnectionError: 거래소 연결이 끊겼다
ex10: 실패 통지 A {symbols=['ETH/USD'], cause=ConnectionError: 거래소 연결이 끊겼다, chained=False}
ex10.derived: generator 정리 {tag=ex10.source}
trading_core.domain: 스테이지가 실패했다 {stage=PriceReq@ex10:...:4, symbols=['BTC']}
  ...
ex10: 실패 통지 B {symbols=['BTC'], cause=StageFailed: 스테이지가 실패했다. - ... ['BTC/USD']: ConnectionError: ..., chained=True}
ex10: A가 실패한 심볼을 update()로 다시 넣는다
ex10.origin: init 2회차 {tag=ex10.source}
ex10.origin: generator 2회차 시작 {tag=ex10.source, upper=['ETH/USD']}
ex10: 수신 A {symbol=ETH/USD}
...
ex10: ----- 2. 소비자 Sender 하나가 던진다 -----
ex10: 수신 C {symbol=BTC/USD}
ex10: 수신 D {symbol=BTC/USD}
...
ex10: 실패 통지 D {symbols=['BTC/USD'], cause=ValueError: D가 데이터를 처리하지 못했다, chained=False}
ex10: 수신 C {symbol=BTC/USD}
ex10: 수신 C {symbol=BTC/USD}
...
ex10: ----- 3. detach 콜백이 던진다 -----
...
ex10.origin: detach {tag=ex10.cleanup}
trading_core.domain: 정리 콜백이 실패했다 {callback=detach}
Traceback (most recent call last):
  ...
RuntimeError: 연결을 닫다가 실패했다
ex10: ----- 4. Domain.stream()이 실패를 만난다 -----
ex10: stream 수신 {symbol=BTC/USD, seq=0}
ex10: stream 수신 {symbol=BTC/USD, seq=1}
ex10: stream 수신 {symbol=BTC/USD, seq=2}
...
ex10: stream()이 StageFailed를 던졌다 {symbols=['BTC/USD']}
ex10: ===== 판정 =====
ex10: 정상: 원천·파생 소비자 모두 실패 통지를 받는다
ex10: 정상: 각 소비자는 자기 심볼만 받는다(A: ETH/USD, B: BTC)
ex10: 정상: 파생 쪽 실패는 상위의 StageFailed로 이어진다(__cause__)
ex10: 정상: 실패한 스테이지는 detach까지 정리된다
ex10: 정상: 코어는 재시도하지 않는다(init 1회)
ex10: 정상: 실패한 심볼은 구독에서 빠진다
ex10: 정상: 다시 넣으면 새 스테이지가 init부터 선다(init 2회)
ex10: 정상: 던진 Sender(D)만 실패 통지를 받는다
ex10: 정상: 원인은 D 자신의 예외다
ex10: 정상: 다른 소비자(C)는 계속 받는다
ex10: 정상: 떼어진 D에는 더 오지 않는다
ex10: 정상: 공유 generator는 재시작하지 않는다
ex10: 정상: 정리 실패가 호출자에게 올라오지 않는다
ex10: 정상: detach 콜백은 불렸다
ex10: 정상: 정리 실패는 소비자 실패가 아니다(on_error 없음)
ex10: 정상: stream()은 StageFailed를 던지고 끝난다
```

(줄 앞의 레벨과 여러 줄로 펼쳐지는 필드는 줄였다.) `실패 통지`는 `WARNING`, 코어의
`스테이지가 실패했다`·`정리 콜백이 실패했다`와 `회귀:` 판정은 `ERROR`로 찍힌다. 코어의 ERROR
줄은 고장이 아니라 이 예제가 일부러 낸 실패의 기록이다.

## 관전 포인트

**원천 합집합은 `{BTC/USD, ETH/USD}`인데 A는 `ETH/USD`만 통지받는다.** `BTC/USD`는 B의 파생이
상위에 등록한 심볼이라 A의 것이 아니다. 실패 통지는 스테이지 전체가 아니라 **소비자 몫의 심볼**
단위다. B는 하위 표기(`BTC`)로 받는다.

**B의 `chained=True`.** 파생 스테이지 자신은 아무것도 던지지 않았다. 상위가 실패해서 내려간
것이고, 그래서 B가 받은 `StageFailed`의 `__cause__`는 원천의 `StageFailed`다. `cause` 문자열에도
원천의 원인이 그대로 들어 있다.

**`init 2회차`는 실패 직후가 아니라 `update()` 뒤에 나온다.** 실패와 재구독 사이 1초 동안
init이 다시 불리지 않는다 — 코어는 재시도하지 않는다. 다시 세울지는 소비자가 정한다.

**2번에서 D가 빠진 뒤에도 `generator ... 시작` 줄이 없다.** C와 D가 같은 심볼을 구독했으므로
D가 빠져도 합집합이 그대로다(ex06의 규칙). 공유 generator는 D의 실패를 모른 채 계속 돈다.

**3번의 `async with`는 예외 없이 빠져나온다.** `detach` 콜백의 실패는 구독을 연 쪽이 다룰 수
있는 일이 아니라서 호출자에게 올리지 않는다. 정리는 끝까지 하고 ERROR 로그만 남는다.

## 어디를 검증하는가

`domain.py`의 공유 스테이지에서 generator를 돌리는 `pump()`와 실패 처리다.

```python
async def pump(gen, seq):
    try:
        async with aclosing(gen):
            async for data in gen:
                await router(data)        # Sender 실패는 SymbolRouter가 그 Sender만 떼고 알린다
    except Exception as exc:
        ...                               # 재시도하지 않는다
        await self._spawn(fail_and_notify(exc, seq), ...)
```

`fail_and_notify()`가 스테이지를 레지스트리에서 빼고(`detach` 포함) 라우터를 비우며 소비자별
`(심볼, on_fail)`을 돌려받아 알린다. 파생이 상위에 등록할 때 넘긴 `on_fail`이 그 파생 스테이지를
다시 실패시키므로 연쇄가 생긴다. 정리 콜백은 `_run_cleanups()`를 거쳐 실패를 로그로만 남긴다.

## 알아둘 점

- `init` 콜백 실패는 ex11이 따로 보인다. 세션 요청(`SessionRequest`)의 슬롯 실패는 이 예제에 없다.
  정책은 같고(`AGENTS.md` 핵심 불변식 7·8), `tests/test_domain.py`의 "실패 정책" 절이 덮는다.
- `on_error`는 언제나 스테이지 락 밖에서 불린다(원천·파생은 별도 태스크, 세션의 init·bind·always
  실패는 락을 놓은 `update()` 안). 여기서 `sub.update()`를 불러도 교착하지 않는다.
  예제는 판정을 단계별로 끊으려고 `run_ex()`에서 다시 넣는다.
- 실패 통지는 비동기다. 예제는 `Consumer.wait_failed()`로 제한 시간을 두고 기다린다 — 회귀가
  실패가 아니라 멈춤으로 나타나지 않게 하려는 것이다.
- `binder`가 버티기로 했다면 generator 안에서 `try`/`except`로 재연결하면 된다. 그러면 코어는
  실패를 보지 못하고, 이 예제의 1·4번은 일어나지 않는다.
