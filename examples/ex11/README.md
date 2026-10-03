# ex11: init 콜백이 던질 때의 처리

ex10은 generator·`Sender`·정리 콜백이 던질 때를 보였다. ex11은 그보다 앞, **스테이지를 세우는
init 콜백이 던질 때**를 다룬다. init은 거래소 로그인·세션 저장소 열기처럼 실패할 수 있는 일을 하기
쉬운 자리다.

정책은 다른 실패와 같다.

> init이 던지면 스테이지를 세우지 않고, 그 스테이지를 쓰려던 소비자에게 **자기 심볼만** 담은
> `StageFailed`를 `on_error`로 알린다. `update()`·`subscribe()`는 던지지 않는다.

예외는 **등록 오류**다. binder가 없는 요청처럼 코드가 잘못된 경우는 init 실패가 아니라서 지금처럼
`DomainError`가 호출자에게 간다. 다시 구독해도 낫지 않는 버그이기 때문이다.

## 파일 구성

- `ex11.py`: 실패를 주입할 수 있는 원천 · 파생 · 세션 요청.
  - 원천 `TickReq(account=...)`: init이 그 계정으로 로그인하는 흉내를 낸다. `REFUSED`에 계정이
    들면 다음 로그인이 한 번 `PermissionError("API 키가 거부되었다")`를 던진다.
  - 파생 `PriceReq(account=...)`: 같은 계정의 `TickReq`를 상위로 둔다(`BTC` → `BTC/USD`). 자기
    init은 늘 성공한다.
  - 세션 `WatchReq(name=...)`: 하위 심볼마다 계정 `{name}:{symbol}`의 원천에 붙는다. 그래서 심볼
    하나의 상위만 실패시킬 수 있다. 자기 init도 `REFUSED`에 `name`이 들면 던진다.
  - `UnboundReq`: binder를 일부러 등록하지 않은 요청.
  - init 시도 · generator 시작 · detach 횟수와 unbind된 심볼을 `계층:이름` 키로 기록한다.
    `run_ex()`가 시작할 때 `reset()`으로 비운다.
- `run_ex.py`: 다섯 시나리오를 돌리고 끝에 판정을 남긴다. 시나리오가 예외로 새어 나오면 그것도
  회귀로 남긴다 — 이 예제가 보이려는 것이 "던지지 않는다"이기 때문이다.

## 시나리오

| # | 무엇이 던지나 | 코어가 하는 일 | 소비자가 보는 것 |
| --- | --- | --- | --- |
| 1 | 원천 init | 스테이지를 세우지 않는다. generator도 detach도 없다 | `on_error`로 요청한 심볼 전부(`BTC/USD`·`ETH/USD`) |
| 2 | 파생의 상위(원천) init | 상위 스테이지가 실패한 것처럼 파생까지 연쇄한다. 파생 generator는 띄우지 않고, 이미 만든 파생 컨텍스트는 detach한다 | `on_error`로 하위 표기 `BTC`. `__cause__`는 상위의 `StageFailed`(`BTC/USD`) |
| 3 | 세션 자신의 init | `subscribe()`는 init을 부르지 않는다. 첫 `update()`가 init하다 실패를 안다 | `update()`가 돌아올 때 이미 `on_error`를 받았다 |
| 4 | 세션 슬롯 하나의 상위 init | 그 상위를 쓰는 슬롯만 닫는다. bind된 슬롯이라 unbind로 짝을 맞춘다 | `ETH`만 `on_error`. `BTC`는 계속 받는다 |
| 5 | (binder 없음) | 등록 오류다. 처리하지 않는다 | `subscribe()`가 `DomainError`를 던진다. `on_error`는 없다 |

1~4는 모두 실패한 심볼을 `update()`로 다시 넣는다. 그러면 init부터 다시 한다(`로그인 2회차`,
`세션 init 2회차`). 코어가 다시 시도한 것이 아니라 소비자가 고른 재구독이다.

## 실행

```bash
uv run python examples/ex11/run_ex.py
uv run examples/main.py ex11
```

```text
ex11: ----- 1. 원천 init이 던진다 -----
ex11.origin: 로그인 1회차 {account=ex11.source}
trading_core.domain: init 콜백이 실패했다 {request=TickReq@ex11:..., content_id=ex11@TickReq:..., symbols=['BTC/USD', 'ETH/USD']}
PermissionError: API 키가 거부되었다
ex11: 실패 통지 A {symbols=['BTC/USD', 'ETH/USD'], cause=PermissionError: API 키가 거부되었다, chained=False}
ex11: A가 실패한 심볼을 update()로 다시 넣는다
ex11.origin: 로그인 2회차 {account=ex11.source}
ex11.origin: generator 시작 {account=ex11.source, upper=['BTC/USD', 'ETH/USD']}
ex11: 수신 A {symbol=BTC/USD}
...
ex11: ----- 2. 파생의 상위(원천) init이 던진다 -----
ex11.origin: 로그인 1회차 {account=ex11.derived}
trading_core.domain: init 콜백이 실패했다 {..., symbols=['BTC/USD']}
PermissionError: API 키가 거부되었다
ex11.derived: detach {account=ex11.derived}
trading_core.domain: 스테이지가 실패했다 {stage=PriceReq@ex11:...:5, symbols=['BTC']}
  ...
ex11: 실패 통지 B {symbols=['BTC'], cause=StageFailed: 스테이지가 실패했다. - ... ['BTC/USD']: PermissionError: ..., chained=True}
ex11: B가 다시 넣는다
ex11.origin: 로그인 2회차 {account=ex11.derived}
ex11.origin: generator 시작 {account=ex11.derived, upper=['BTC/USD']}
ex11.derived: generator 시작 {account=ex11.derived, lower=['BTC']}
ex11: 수신 B {symbol=BTC}
...
ex11: ----- 3. 세션 자신의 init이 던진다 -----
ex11.session: 세션 init 1회차 {name=ex11.session}
trading_core.domain: init 콜백이 실패했다 {stage=WatchReq@ex11:...:9, symbols=['BTC']}
PermissionError: 세션 저장소를 열지 못했다
ex11: 실패 통지 C {symbols=['BTC'], cause=PermissionError: 세션 저장소를 열지 못했다, chained=False}
ex11: C가 다시 넣는다
ex11.session: 세션 init 2회차 {name=ex11.session}
ex11.session: bind {name=ex11.session, symbol=BTC}
...
ex11: ----- 4. 세션 슬롯의 상위 init이 던진다 -----
ex11.session: 세션 init 1회차 {name=ex11.slot}
ex11.session: bind {name=ex11.slot, symbol=BTC}
ex11.session: bind {name=ex11.slot, symbol=ETH}
ex11.origin: 로그인 1회차 {account=ex11.slot:BTC}
ex11.origin: 로그인 1회차 {account=ex11.slot:ETH}
trading_core.domain: init 콜백이 실패했다 {..., symbols=['ETH/USD']}
PermissionError: API 키가 거부되었다
ex11.origin: generator 시작 {account=ex11.slot:BTC, upper=['BTC/USD']}
ex11: 수신 D {symbol=BTC}
ex11.session: unbind {name=ex11.slot, symbol=ETH}
trading_core.domain: 세션 슬롯이 실패했다 {stage=WatchReq@ex11:...:12, symbols=['ETH']}
  ...
ex11: 실패 통지 D {symbols=['ETH'], cause=StageFailed: ... ['ETH/USD']: PermissionError: ..., chained=True}
ex11: 수신 D {symbol=BTC}
ex11: 수신 D {symbol=BTC}
ex11: D가 ETH를 다시 넣는다
...
ex11: ----- 5. binder가 없는 요청(등록 오류) -----
ex11: subscribe()가 DomainError를 던졌다 {error=지원 되는 요청이 아니거나 등록된 요청이 아니다. - unregistered}
ex11: ===== 판정 =====
ex11: 정상: update()는 init 실패를 던지지 않는다
ex11: 정상: 요청한 심볼 모두의 실패를 알린다
ex11: 정상: 원인은 init이 던진 예외다
ex11: 정상: 스테이지가 서지 않는다(공유 심볼·generator·detach 없음)
ex11: 정상: 다시 넣으면 init부터 다시 한다(로그인 2회차)
ex11: 정상: update()는 상위 init 실패도 던지지 않는다
ex11: 정상: 파생 소비자가 실패 통지를 받는다
ex11: 정상: 파생 소비자는 자기 하위 표기 심볼(BTC)로 받는다
ex11: 정상: __cause__는 상위의 StageFailed(BTC/USD)다
ex11: 정상: 파생 generator는 시작하지 않고, 파생 컨텍스트는 detach된다
ex11: 정상: 파생 스테이지에 심볼이 남지 않는다
ex11: 정상: 다시 넣으면 상위부터 다시 선다
ex11: 정상: subscribe()는 init을 부르지 않는다
ex11: 정상: update()는 세션 init 실패를 던지지 않는다
ex11: 정상: update()가 돌아올 때 이미 알렸다(기다리지 않음)
ex11: 정상: 다음 update()가 init을 다시 한다(세션 init 2회차)
ex11: 정상: update()는 슬롯 상위 init 실패를 던지지 않는다
ex11: 정상: ETH만 실패 통지를 받는다(하위 표기)
ex11: 정상: bind된 ETH 슬롯은 unbind로 짝을 맞춘다
ex11: 정상: BTC는 계속 받는다
ex11: 정상: 다시 넣은 ETH도 받는다
ex11: 정상: 등록 오류는 DomainError로 호출자에게 간다
ex11: 정상: 등록 오류는 on_error로 오지 않는다
```

(줄 앞의 레벨과 여러 줄로 펼쳐지는 필드·traceback은 줄였다.) `실패 통지`는 `WARNING`, 코어의
`init 콜백이 실패했다`·`스테이지가 실패했다`·`세션 슬롯이 실패했다`와 `회귀:` 판정은 `ERROR`로
찍힌다. 코어의 ERROR 줄은 고장이 아니라 이 예제가 일부러 낸 실패의 기록이다.

## 관전 포인트

**1번에는 `generator 시작`도 `detach`도 없다.** init이 던졌으니 컨텍스트가 없고, 컨텍스트가 없으니
돌릴 generator도 정리할 것도 없다. 스테이지 자체가 레지스트리에 들어가지 않는다.

**2번의 `ex11.derived: detach`는 있는데 `ex11.derived: generator 시작`은 없다.** 파생 자신의 init은
성공해 컨텍스트가 생겼으므로 detach로 정리한다. 하지만 상위를 세우지 못했으니 받을 데이터가 없는
generator는 띄우지 않는다. B가 받는 실패는 상위 스테이지가 실행 중에 죽었을 때(ex10의 1번)와 같은
모양이다 — 하위 표기 `BTC`, `chained=True`.

**3번의 `세션 init 1회차`는 `subscribe()`가 아니라 `update()` 뒤에 나온다.** 세션도 원천·파생처럼
init을 첫 `update()`로 미룬다. 그래서 init 실패를 알릴 심볼이 생기고, `subscribe()`는 init 때문에
던질 일이 없다. 세션의 실패는 `update()`가 락을 놓은 뒤 그 자리에서 알리므로, 판정은
기다리지 않고 `update()` 직후에 확인한다.

**4번에서 `unbind ETH`가 실패 통지보다 먼저다.** `ETH` 슬롯은 bind까지 끝난 뒤에 상위가 서지 못했다.
그래서 슬롯을 닫으며 unbind로 bind와 짝을 맞춘다(핵심 불변식 6). `BTC` 슬롯과 그 상위는 건드리지
않는다.

**5번만 `on_error`가 아니라 예외다.** 1~4는 다시 구독하면 나을 수 있는 실행 중 실패라 구독 단위로
알린다. binder가 없는 것은 코드의 버그라 다시 해도 같으므로 바로 던진다.

## 어디를 검증하는가

원천·파생은 `domain.py`의 `_update_shared_stage()`다. 스테이지가 없으면 만들고, 만들다 init이
던지면 스테이지를 두지 않고 그 센더의 `on_fail`로 요청 심볼의 실패를 알린다.

```python
stage = self._shared_stages.get(req.tr_content_id)
if stage is None:
    if not symbols:
        return True
    try:
        stage = self._get_or_create_shared_stage(req)
    except _InitFailed as failed:           # init 예외만. binder 누락 같은 DomainError는 그대로 올라간다
        ...
        if on_fail is not None:
            await on_fail(set(symbols), failed.exc)
        return False
```

파생은 상위를 이 함수로 세운다. 상위의 `on_fail`이 파생 스테이지를 실패로 내리므로(ex10의 연쇄와
같은 경로) 2번이 생기고, `False`를 받으면 파생 generator를 띄우지 않는다. 세션의 상위 구독도 이
함수를 거치므로 4번은 세션의 상위 실패 처리(`on_upstream_failed()`)가 그 상위를 쓰는 슬롯만 닫는다.
세션 자신의 init은 `_create_session_subscription()`의 `apply()`가 첫 `update()`에서 부른다.

## 알아둘 점

- 1·2·4번의 실패 통지는 코어가 띄운 태스크에서 오므로 `update()`가 돌아온 뒤에 도착한다. 예제는
  `Consumer.wait_failed()`로 제한 시간을 두고 기다린다. 3번(세션 자신의 init)만 `update()`가 돌아올
  때 이미 와 있다.
- init 안에서 버틸지(로그인 재시도 등)는 binder가 정한다. init이 스스로 재시도하고 끝내 던지지
  않으면 코어는 실패를 보지 못한다.
- init이 던지면 detach 콜백은 불리지 않는다. init 안에서 일부 자원을 열었다가 던진다면 그 자원은
  init이 `try`/`except`로 직접 닫아야 한다.
- `stream()`으로 소비하면 init 실패도 `StageFailed`로 던져진다(ex10의 4번과 같다).
