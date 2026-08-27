# ex08: 같은 `content_id`라도 `RequestModel`은 공유되지 않는다

이 예제가 보여 주는 것은 이 한 문장이다.

> `RequestModel`은 두 요청이 같은 내용의 요청이라도(같은 content_id) 서로 다른 요청으로
> 취급하며 컨텍스트를 공유하지 않는다.

ex01~ex06에서 "content_id가 같으면 원천 하나를 공유한다"는 것은 프레임워크의 1번
불변식이었다. 필드 값이 같은 요청을 두 소비자가 보내면 `Domain`은
`_origin_stage_dict[content_id]`에 있는 스테이지를 재사용하고, init 콜백은 한 번만
불리며, 컨텍스트와 generator를 함께 쓴다.

`RequestModel`(instanter)에는 그 규칙이 적용되지 않는다. **요청을 보낸 수만큼 스테이지가
생기고, 스테이지마다 init 콜백이 다시 불려 자기 컨텍스트를 갖는다.** content_id가 같아도,
구독한 심볼까지 똑같아도 마찬가지다.

## 세 계층을 한 화면에 겹쳐 놓는다

| 계층 | 요청 | 두 소비자가 같은 내용으로 요청하면 |
| --- | --- | --- |
| 요청형 | `WatchReq(quote="USD")` | 스테이지 **둘**, 컨텍스트 **둘**, `"BTC"` 슬롯 **둘** |
| 원천 | `BeatReq()` | 스테이지 **하나**, 컨텍스트 **하나**, generator **하나** |

두 소비자의 요청형 스테이지가 각각 상위 `BeatReq`를 구독하는데, 그 상위는 여전히
content_id 단위로 공유된다. 공유가 사라진 것이 아니라 **공유의 경계가 요청형 스테이지
아래로 내려간 것**이다.

## 파일 구성

- `ex08.py`: 원천 `BeatReq`와 요청형 `WatchReq` 한 쌍. 양쪽 init 콜백이 자기가 몇 번째로
  불렸는지 출력한다.
- `run_ex.py`: 내용이 같은 `WatchReq` 두 개를 같은 심볼 `{"BTC"}`로 동시에 구독한다.

## 예제의 흐름

1. `WatchReq(quote="USD")`를 두 개 만든다. `content_id`를 비교해 같음을 먼저 출력한다.
2. 소비자 A와 B가 각각 그 요청을 `{"BTC"}`로 구독한다.
3. `WatchCtx`가 **두 번** 만들어지고 bind 콜백도 **두 번** 불린다. 같은 content_id, 같은
   심볼인데도 그렇다.
4. 두 시퀀스는 모두 상위 표기 `"BTC/USD"`로 `BeatReq`를 구독한다. 상위는 content_id
   단위로 공유되므로 `BeatCtx`는 **한 번만** 만들어진다.
5. 원천이 발행한 틱은 두 슬롯 모두로 라우팅되고, 각 슬롯의 `WatchRunnable`이 자기
   컨텍스트의 `seen`을 올린다.
6. 각 소비자가 3건씩 받고 빠지면 슬롯이 하나씩 닫히며 unbind → detach가 스테이지마다
   따로 불린다.

## 실행

```bash
uv run python examples/ex08/run_ex.py
```

```text
[ex08] content_id가 같은가: True
[ex08] WatchCtx 생성 #1 - content_id=ex08@WatchReq:3ab87c06fb23bd9d
[ex08] bind   ctx#1 symbol=BTC
[ex08] WatchCtx 생성 #2 - content_id=ex08@WatchReq:3ab87c06fb23bd9d
[ex08] bind   ctx#2 symbol=BTC
[ex08] BeatCtx 생성 #1
  [수신 B] ctx#2 seen=1 BTC=100.0
  [수신 A] ctx#1 seen=1 BTC=100.0

----- 원천 `BeatReq` 스테이지: 공유됨, 상위 심볼={'BTC/USD'} -----
----- 요청형 `WatchReq` 스테이지: 공유 레지스트리에 없음 -----

  [수신 B] ctx#2 seen=2 BTC=101.0
  [수신 A] ctx#1 seen=2 BTC=101.0
  [수신 B] ctx#2 seen=3 BTC=102.0
  [수신 A] ctx#1 seen=3 BTC=102.0
[ex08] unbind ctx#2 symbol=BTC
[ex08] unbind ctx#1 symbol=BTC
[ex08] detach ctx#2 seen=3
[ex08] detach ctx#1 seen=3
```

(위는 `TaskManager`의 `[TASK ...]` 진단 출력을 뺀 것이다. content_id 앞의 모듈 이름은
실행 방식에 따라 달라진다 — `examples/main.py ex08`로 돌리면 `ex08.ex08@WatchReq`가 된다.
중요한 것은 **두 줄의 content_id가 서로 같다**는 점이다.)

## 관전 포인트

**`WatchCtx 생성`이 두 번, content_id는 같다.** 이 예제의 전부가 이 두 줄에 있다.
같은 content_id로 두 번 요청했는데 init 콜백이 두 번 불렸다. 원천이었다면 두 번째
요청은 첫 번째가 만든 스테이지를 그대로 받았을 것이다.

**`seen`이 둘 다 1, 2, 3이다.** 컨텍스트가 공유된다면 두 소비자의 수신이 하나의 카운터에
섞여 1~6이 번갈아 찍혔을 것이다. 따로 1~3을 센다는 것은 `WatchCtx` 객체가 실제로 둘이라는
뜻이다. 스테이지별 상태(구독 시퀀스 번호, 인증 토큰, 재연결 카운터 같은 것)를 컨텍스트에
두려 할 때 알아 두어야 하는 성질이다.

**`BeatCtx 생성`은 한 번뿐이다.** 요청형이 공유되지 않는다고 해서 그 위의 원천까지
복제되지는 않는다. 두 스테이지가 각각 만든 시퀀스가 모두 `"BTC/USD"`를 요구하고, 그
합집합은 `{"BTC/USD"}` 하나이므로 원천 generator도 하나만 돈다.

**두 번째 구독이 원천을 재시작시키지 않는다.** B가 붙어도 상위 합집합은
`{"BTC/USD"}` 그대로다. 3번 불변식("합집합이 바뀔 때만 재시작")이 그대로 적용되어
`[TASK SUBMIT]`은 `BeatReq` 이름으로 한 번만 찍힌다. A가 먼저 빠질 때도 마찬가지로
재시작이 없고, B까지 빠져 합집합이 비어야 원천이 정리된다.

**unbind와 detach가 스테이지마다 따로 불린다.** 슬롯도 컨텍스트도 스테이지 소유이므로
정리도 스테이지 단위다. `ctx#1`과 `ctx#2`가 각각 자기 `"BTC"` 슬롯을 닫는다.

## 왜 이렇게 되어 있나

원천·파생의 공유는 "같은 요청이면 같은 데이터"라는 전제 위에 서 있다. generator 하나가
심볼 합집합을 통째로 받아 돌고, 출력은 심볼로 fan-out하면 되므로 소비자를 구분할 필요가
없다.

요청형은 전제가 다르다. 슬롯이 심볼 단위이고 각 슬롯이 자기 `Runnable` 상태를 들고
있다(ex07의 `SwingRunnable.active_price`). 두 소비자가 같은 심볼을 구독했더라도 그
상태를 공유하는 것이 옳다는 보장이 없다. 그래서 instanter는 공유를 아래 계층에 맡기고,
자신은 요청마다 독립적으로 선다.

## 알아둘 점

- 컨텍스트를 정말 공유해야 한다면 `WatchCtx`가 아니라 그 아래 원천 요청의 컨텍스트에
  두어야 한다. 요청형 컨텍스트는 소비자별 상태를 두는 자리다.
- 요청형 스테이지가 늘어난다고 상위 연결이 늘어나지는 않는다. 늘어나는 것은 슬롯과
  라우팅 대상이고, 상위 generator 수는 상위 표기 합집합이 정한다.
- 소비자가 많아질수록 요청형 스테이지도 그만큼 생긴다. 슬롯마다 `TransmitQueue`와 태스크가
  하나씩 붙으므로, 같은 요청을 아주 많은 소비자가 동시에 열 계획이라면 이 비용을 감안해야
  한다.

## 어디를 검증하는가

`domain.py`의 `_define_inst_stage()`다. 원천 쪽 `_define_origin_gen_stage()`와 나란히
놓으면 차이가 한눈에 보인다.

```python
def _define_origin_gen_stage(self, req: BaseReqModel):
    content_id = req.get_tr_content_id()
    if origin_stage := self._origin_stage_dict.get(content_id):
        return origin_stage          # ← content_id로 재사용한다
    ...
    ctx = bind_pack.get_init_cb()(req)

def _define_inst_stage(self, req: BaseReqModel, output: Sender):
    ...                              # ← `_origin_stage_dict`를 보지 않는다
    ctx = bind_pack.get_init_cb()(req)   # 호출마다 새 컨텍스트
```

`_define_inst_stage()`에는 content_id로 스테이지를 되찾는 경로도, 만든 스테이지를
`_origin_stage_dict`에 넣는 줄도 없다. `run_ex.py`의 `report_registry()`가 그것을 그대로
확인한다 — `BeatReq`의 content_id로는 `get_origin_stage()`가 스테이지를 돌려주지만,
`WatchReq`의 content_id로는 `KeyError`가 난다.
