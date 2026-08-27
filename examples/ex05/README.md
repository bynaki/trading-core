# ex05: 같은 파생 요청을 서로 다른 심볼로 동시에 구독하기

파생 요청(`DependentModel`)을 여러 소비자가 **서로 다른 심볼 집합으로 동시에** 구독하는
상황을 다룬다. ex04가 요청을 순차로 실행하는 것과 달리, 여기서는 구독을 열어 둔 채 다른
구독을 붙였다 뗀다.

보여 주는 것은 이 불변식이다.

> 파생 스테이지가 상위 원천에 등록하는 심볼은 **구독자 전체의 합집합**이어야 한다.

구독자가 붙고 떠날 때마다 상위 등록이 어떻게 다시 계산되는지를 로그와 수신 건수로
따라갈 수 있게 만든 예제다. 실행하면 A·B가 각자 자기 심볼을 계속 받고, 상위에는 둘의
합집합이 올라가고, B가 떠나면 A의 몫만 남는 것이 그대로 보인다.

원래 이 불변식이 깨져 있었고([원인과 해결](#원인과-해결)), 그 결함을 재현하려고 만든
예제였다. 지금은 고쳐졌으므로 **정상 동작을 보여 주는 예제**이자 회귀를 잡는 감시
장치다. 마지막 판정 두 줄이 `정상:`이면 불변식이 지켜지고 있다는 뜻이고, 깨지면
`회귀:`로 바뀐다.

## 파일 구성

- `ex05.py`: ex04를 최소화한 원천(`TickRequest`) · 파생(`PriceRequest`) 한 쌍.
  각 콜백이 자신이 어떤 심볼로 (재)시작했는지 출력한다.
- `run_ex.py`: A·B 두 구독자를 시간차로 붙였다 떼며 단계별 수신 건수를 세고 판정한다.

## 시나리오

`Domain.request()` 대신 저수준 `Domain.stage()`를 쓴다. 구독을 열어 둔 채 다른 구독을
붙였다 떼야 하고, 데이터가 오지 않는 구독자도 블로킹 없이 관찰해야 하기 때문이다.
(`Domain.request()`의 `async for`는 데이터가 없으면 그대로 멈춰 있어, 한쪽이 아무것도
받지 못하는 상황 자체를 관찰할 수 없다.)

| 단계 | 상태 | 상위 원천에 등록되어야 하는 심볼 |
| --- | --- | --- |
| 1단계 | A가 `{"BTC"}` 단독 구독 | `{BTC/USD}` |
| 2단계 | A `{"BTC"}` + B `{"ETH"}` 동시 구독 | `{BTC/USD, ETH/USD}` |
| 3단계 | B 구독 해제, A만 남음 | `{BTC/USD}` |

두 구독자의 요청은 `PriceRequest(quote="usd")`로 같다. `content_id`가 같으니 하나의
파생 스테이지를 공유하고, 심볼은 `SendRouter`가 합집합으로 관리한다.

## 실행

```bash
uv run python examples/ex05/run_ex.py
```

```text
----- 1단계: A가 {"BTC"} 단독 구독 -----
[REQUIRE]   하위 ['BTC'] -> 상위 ['BTC/USD']
[ORIGIN]    generator (재)시작 — 상위 구독 심볼 = ['BTC/USD']
[DEPENDENT] generator (재)시작 — 하위 구독 심볼 = ['BTC']
  [수신 A] BTC = 68,000.0 (seq=0)
  ...

----- 2단계: A{"BTC"} + B{"ETH"} 동시 구독 -----
[REQUIRE]   하위 ['BTC', 'ETH'] -> 상위 ['BTC/USD', 'ETH/USD']
[ORIGIN]    generator (재)시작 — 상위 구독 심볼 = ['BTC/USD', 'ETH/USD']
[DEPENDENT] generator (재)시작 — 하위 구독 심볼 = ['BTC', 'ETH']
  [수신 A] BTC = 68,000.0 (seq=0)
  [수신 B] ETH = 3,200.0 (seq=0)
  ...

----- 3단계: B 구독 해제, A만 남음 -----
[REQUIRE]   하위 ['BTC'] -> 상위 ['BTC/USD']
[ORIGIN]    generator (재)시작 — 상위 구독 심볼 = ['BTC/USD']
[DEPENDENT] generator (재)시작 — 하위 구독 심볼 = ['BTC']
  [수신 A] BTC = 68,000.0 (seq=0)
  ...

===== 단계별 수신 건수 =====
                                           A       B
1단계: A가 {"BTC"} 단독 구독               4       0
2단계: A{"BTC"} + B{"ETH"} 동시 구독       6       6
3단계: B 구독 해제, A만 남음               4       0

===== 판정 =====
정상: A는 B가 붙은 뒤에도 계속 데이터를 받는다.
정상: B가 떠난 뒤 A의 상위 구독이 남아 있다.
```

**`[DEPENDENT]` 줄과 `[ORIGIN]` 줄의 심볼이 서로 대응하는지**가 관전 포인트다. 2단계에서
하위가 `['BTC', 'ETH']`면 상위도 `['BTC/USD', 'ETH/USD']`여야 한다. 위 출력에서는 세 단계
모두 두 줄이 맞물려 있다.

두 줄이 어긋나면 파생 스테이지는 A에게 BTC를 넘길 준비가 되어 있는데 상위에 BTC를 요청한
적이 없는 상태가 된다. 그러면 A는 예외도 경고도 없이 데이터만 끊긴다 — 아래 결함의
증상이 정확히 이것이었다.

## 원인과 해결

결함이 있던 시절 `domain.py`의 `dependent_generator` 브랜치는 이랬다.

```python
async def update(sender: Sender, symbols: set[str]):
    async with update_lock:
        require, req_symbols = req.get_tr_require_with_symbol(symbols)  # <-- 이번 update뿐
        shared_sender.set_sender(sender, symbols)
        current_symbols = shared_sender.symbols                          # <-- 합집합
        ...
        await self._ensure_require_stage(require, transq, req_symbols)   # <-- 합집합 아님
        gen = binded_cb(ctx, set(current_symbols))                       # <-- 합집합
```

한 스테이지 안에 심볼 집합이 두 개 돌아다녔다. 파생 binder에는 합집합(`current_symbols`)이
가는데, 상위 원천에는 그 시점 update의 심볼만 변환한 `req_symbols`가 갔다.

게다가 상위 원천에 등록하는 `Sender`는 이 파생 스테이지의 `transq` **하나뿐**이다.
`SendRouter.set_sender()`는 같은 sender의 이전 등록을 지우고 새로 넣으므로, 두 번째
update의 `req_symbols`가 첫 번째 것을 통째로 덮어썼다. 구독자별로 쌓이지 않는다.

증상은 두 가지였다.

1. 2단계에서 상위에 `['ETH/USD']`만 남아 A가 한 건도 받지 못한다.
2. 3단계에서 B가 떠날 때 빈 집합이 상위에 등록되어 **원천 스테이지가 완전히 해제**된다.
   A만 남아도 되살아나지 않는다. 한 번 어긋나면 자가 복구가 안 됐다.

해결은 `require` 변환의 입력을 합집합이 확정된 **뒤에** 잡는 것이다.

```diff
             async def update(sender: Sender, symbols: set[str]):
                 nonlocal active_symbols, gen
                 async with update_lock:
-                    require, req_symbols = req.get_tr_require_with_symbol(symbols)
                     shared_sender.set_sender(sender, symbols)
                     current_symbols = shared_sender.symbols
                     if current_symbols == active_symbols:
                         return
+                    require, req_symbols = req.get_tr_require_with_symbol(current_symbols)
```

`set_sender()` 뒤로 옮기는 것이 핵심이다. 파생 binder가 이미 합집합을 받고 있으니,
상위에도 같은 기준을 적용해 두 계층을 일치시킨다.

### 전제

`require` 콜백은 **심볼에 따라 다른 상위 요청을 반환하면 안 된다.** 파생 스테이지는
`transq` 하나로 상위 하나만 바라보므로, 심볼별로 원천을 갈라야 하는 요구가 생기면
상위 스테이지를 여러 개 들 수 있는 구조가 따로 필요하다. ex04처럼 요청 필드(`quote`)로만
상위가 갈리는 형태는 `content_id`가 달라 파생 스테이지 자체가 분리되므로 무관하다.
