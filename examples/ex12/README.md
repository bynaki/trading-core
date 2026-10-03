# ex12: binder가 심볼 하나를 거부할 때의 처리

원천 generator는 심볼 합집합 하나로 돈다. 한 소비자가 넣은 심볼이 상장 폐지되었거나 오타라서
binder가 그냥 예외를 던지면 스테이지 전체의 실패가 되어, 같은 원천을 쓰는 **모든** 소비자가
실패한다(ex10의 1번). binder가 그 심볼을 `SymbolRejected`로 던지면 코어가 피해를 그 심볼로 좁힌다.

> 그 심볼만 구독에서 빼고, 그 심볼을 구독한 소비자에게만 **자기 심볼만** 담은 `StageFailed`를
> `on_error`로 알린다. 스테이지는 남은 심볼로 generator를 다시 띄운다.

binder가 할 일은 어느 심볼을 줄 수 없는지 알려 주는 것뿐이다. 거래소의 오류 응답에서 그 심볼을
읽어 낼 수 있는 것은 binder이기 때문이다. 나머지(구독에서 빼기, 소비자에게 알리기, 남은 심볼로
다시 띄우기, 파생·세션으로 연쇄하기)는 코어가 한다.

```python
if delisted := symbols & DELISTED.get(ctx.account, set()):
    raise SymbolRejected(delisted, "상장 폐지")
```

## 파일 구성

- `ex12.py`: 심볼을 거부하는 원천과 그 위의 파생 · 세션 요청.
  - 원천 `TickReq(account=...)`: generator가 시작하자마자 `LISTED`에 없는 심볼을 "거래소에 없는
    심볼"로 거부한다. 도는 중에는 `DELISTED`에 든 심볼을 "상장 폐지"로 거부한다.
  - 파생 `PriceReq(account=...)`: 같은 계정의 `TickReq`를 상위로 둔다(`BTC` → `BTC/USD`). 거부를
    모른다.
  - 세션 `WatchReq(account=...)`: 하위 심볼마다 슬롯 하나가 같은 계정의 `TickReq`에 붙는다.
  - generator가 받은 심볼, detach 횟수, unbind된 심볼을 `계층:계정` 키로 기록한다. `run_ex()`가
    시작할 때 `reset()`으로 비운다.
- `run_ex.py`: 네 시나리오를 돌리고 끝에 판정을 남긴다. 시나리오마다 계정을 달리해 스테이지를
  따로 세운다.

## 시나리오

| # | 무엇이 거부되나 | 코어가 하는 일 | 소비자가 보는 것 |
| --- | --- | --- | --- |
| 1 | 원천이 도는 중에 `DOGE/USD`(상장 폐지) | `DOGE/USD`만 빼고 `BTC/USD`·`ETH/USD`로 다시 띄운다. detach하지 않는다 | `DOGE/USD`를 구독한 A·B만 `DOGE/USD`의 실패. A는 `BTC/USD`, B는 `ETH/USD`를 계속 받는다 |
| 1′ | A가 `DOGE/USD`를 다시 넣음 | 합집합이 바뀌어 다시 띄우고, binder가 또 거부한다 | A가 두 번째 실패 통지를 받는다 |
| 2 | 구독하자마자 오타 `BTCC/USD` | `BTCC/USD`만 빼고 `BTC/USD`로 다시 띄운다 | C는 `BTCC/USD`의 실패만 받고 `BTC/USD`는 받는다 |
| 3 | 파생의 상위가 `DOGE/USD` | 상위는 1번처럼 처리한다. 파생은 상위 표기를 하위 표기 `DOGE`로 되돌려 그것만 빼고, `BTC`로 다시 띄운다 | D는 하위 표기 `DOGE`의 실패. `__cause__`는 상위의 `StageFailed`(`DOGE/USD`) |
| 4 | 세션 슬롯이 붙은 상위가 `DOGE/USD` | `DOGE` 슬롯만 닫고 unbind한다 | E는 `DOGE`의 실패만 받고 `BTC`는 계속 받는다 |

## 실행

```bash
uv run python examples/ex12/run_ex.py
uv run examples/main.py ex12
```

```text
ex12: ----- 1. 원천이 상장 폐지된 심볼을 거부한다 -----
ex12.origin: generator 시작 {account=ex12.source, upper=['BTC/USD', 'DOGE/USD', 'ETH/USD']}
...
ex12: 거래소가 DOGE/USD를 상장 폐지한다
ex12.origin: generator 정리 {account=ex12.source}
trading_core.domain: 심볼이 실패해 구독에서 뺐다 {stage=TickReq@ex12:...:3, symbols=['DOGE/USD']}
SymbolRejected: 심볼을 줄 수 없다. - ['DOGE/USD']: 상장 폐지
ex12.origin: generator 시작 {account=ex12.source, upper=['BTC/USD', 'ETH/USD']}
ex12: 실패 통지 A {symbols=['DOGE/USD'], cause=SymbolRejected: 심볼을 줄 수 없다. - ['DOGE/USD']: 상장 폐지, chained=False}
ex12: 실패 통지 B {symbols=['DOGE/USD'], ...}
ex12: 수신 A {symbol=BTC/USD}
ex12: 수신 B {symbol=ETH/USD}
ex12: A가 DOGE/USD를 다시 넣는다
...
ex12: ----- 2. 오타 심볼로 구독한다 -----
ex12.origin: generator 시작 {account=ex12.typo, upper=['BTC/USD', 'BTCC/USD']}
trading_core.domain: 심볼이 실패해 구독에서 뺐다 {..., symbols=['BTCC/USD']}
ex12.origin: generator 시작 {account=ex12.typo, upper=['BTC/USD']}
ex12: 실패 통지 C {symbols=['BTCC/USD'], cause=SymbolRejected: ... 거래소에 없는 심볼, chained=False}
ex12: 수신 C {symbol=BTC/USD}
...
ex12: ----- 3. 파생의 상위가 심볼을 거부한다 -----
...
trading_core.domain: 심볼이 실패해 구독에서 뺐다 {stage=TickReq@ex12:...:8, symbols=['DOGE/USD']}
ex12.origin: generator 시작 {account=ex12.derived, upper=['BTC/USD']}
trading_core.domain: 심볼이 실패해 구독에서 뺐다 {stage=PriceReq@ex12:...:7, symbols=['DOGE']}
ex12.derived: generator 시작 {account=ex12.derived, lower=['BTC']}
ex12: 실패 통지 D {symbols=['DOGE'], cause=StageFailed: ... ['DOGE/USD']: SymbolRejected: ..., chained=True}
...
ex12: ----- 4. 세션 슬롯이 붙은 상위가 심볼을 거부한다 -----
...
ex12.session: unbind {account=ex12.session, symbol=DOGE}
trading_core.domain: 세션 슬롯이 실패했다 {stage=WatchReq@ex12:...:9, symbols=['DOGE']}
ex12: 실패 통지 E {symbols=['DOGE'], ...}
ex12: 수신 E {symbol=BTC}
ex12: ===== 판정 =====
ex12: 정상: DOGE/USD를 구독한 A·B가 실패 통지를 받는다
ex12: 정상: 각자 DOGE/USD만 받는다(다른 심볼은 실패가 아니다)
ex12: 정상: 원인은 binder가 던진 SymbolRejected(상장 폐지)다
ex12: 정상: 스테이지는 내려가지 않고 남은 심볼로 다시 돈다
ex12: 정상: A는 BTC/USD, B는 ETH/USD를 계속 받는다
ex12: 정상: 다시 넣어도 binder가 또 거부한다(다시 넣을지는 소비자, 줄지는 binder가 정한다)
ex12: 정상: 오타 심볼(BTCC/USD)만 실패 통지를 받는다
ex12: 정상: 원인은 '거래소에 없는 심볼'이다
ex12: 정상: 같이 넣은 BTC/USD는 받는다
ex12: 정상: 파생 소비자가 실패 통지를 받는다
ex12: 정상: 하위 표기 DOGE만 받고, __cause__는 상위의 StageFailed(DOGE/USD)다
ex12: 정상: 파생은 남은 BTC로 다시 돌고 계속 받는다
ex12: 정상: DOGE만 실패 통지를 받는다(하위 표기)
ex12: 정상: bind된 DOGE 슬롯은 unbind로 짝을 맞춘다
ex12: 정상: BTC는 계속 받는다
```

(줄 앞의 레벨과 여러 줄로 펼쳐지는 필드·traceback은 줄였다.) `실패 통지`는 `WARNING`, 코어의
`심볼이 실패해 구독에서 뺐다`·`세션 슬롯이 실패했다`와 `회귀:` 판정은 `ERROR`로 찍힌다. 코어의
ERROR 줄은 고장이 아니라 이 예제가 일부러 낸 실패의 기록이다.

## 관전 포인트

**1번에서 `generator 정리` 뒤에 `generator 시작`이 바로 온다. `detach`는 없다.** `SymbolRejected`를
던지면 generator는 끝난다. 코어는 그 심볼을 뺀 합집합으로 다시 띄운다. 소비자가 심볼을 바꿔
합집합이 바뀌었을 때와 같은 재시작이다(핵심 불변식 3). 스테이지와 컨텍스트는 그대로라 detach도
init도 다시 하지 않는다.

**1′에서 코어는 다시 시도하지 않는다.** A가 `DOGE/USD`를 다시 넣었기 때문에 합집합이 바뀌어
다시 띄웠고, 줄 수 있는지는 binder가 또 판단해 거부했다. 다시 넣을지는 소비자가, 줄 수 있는지는
binder가 정한다.

**3번에는 `심볼이 실패해 구독에서 뺐다`가 두 번 나온다.** 먼저 원천이 `DOGE/USD`를 빼고, 그 실패를
받은 파생이 하위 표기 `DOGE`로 되돌려 뺀다. 파생은 스스로 거부한 게 아니어도 남은 `BTC`로 다시
뜬다. 파생 binder가 받은 `symbols` 전체를 전제로 돌고 있을 수 있기 때문이다.

**4번은 세션이 원래 하던 대로다.** 상위가 실패를 상위 표기 `DOGE/USD`로 알리면 그 심볼을 쓰던
슬롯(`DOGE`)만 닫는다. 상위가 심볼 하나만 알려 주면 그 슬롯 하나만 닫히는 것이다.

## 어디를 검증하는가

`domain.py`의 `_get_or_create_shared_stage()` 안 `fail_and_notify()`다. generator가 던진 예외가
`SymbolRejected`이고 그 심볼 중 지금 구독된 것이 있으면, 스테이지 전체를 내리는 대신 그 심볼만
뺀다.

```python
rejected = (
    exc.symbols & router.symbols if isinstance(exc, SymbolRejected) else set()
)
if rejected:
    drained = await fail_symbols(rejected, exc)   # 그 심볼만 빼고 sync()로 다시 띄운다
else:
    drained = await fail(exc)                     # 스테이지 전체의 실패
```

파생은 `fail_upstream_symbols()`가 상위의 실패 심볼을 하위 심볼로 되돌린다. 하위 심볼마다
`resolve_upstream({s})`로 상위 표기를 구해 실패 집합과 겹치는 것을 고른다. 모두 겹치면(상위
스테이지 전체가 실패했으면) 지금처럼 파생 스테이지 전체가 실패한다.

## 알아둘 점

- 구독하지 않은 심볼만 거부하면 스테이지 전체의 실패로 본다. 뺄 심볼이 없어 같은 합집합으로
  다시 띄우면 거부가 끝없이 되풀이될 수 있기 때문이다.
- 거부하면 나머지 심볼도 재연결한다. 재시작은 소비자가 심볼을 바꿀 때마다 이미 일어나므로
  binder는 원래 재시작을 견뎌야 한다.
- 파생의 require 콜백이 심볼을 하나씩 바꾼다고 본다(`BTC` → `BTC/USD`). 여러 심볼을 묶어 상위 심볼
  하나로 바꾸는 require라면 되돌리지 못하고, 그때는 파생 스테이지 전체의 실패로 본다.
- `SymbolRejected`가 아닌 예외는 지금처럼 스테이지 전체의 실패다(ex10).
- `stream()`으로 소비하면 심볼 하나의 거부도 `StageFailed`로 던져지고 끝난다.
