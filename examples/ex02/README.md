# ex02: `RequestModel.require()`로 원천 데이터 공유하기

이 예제는 한 요청이 다른 요청의 데이터를 필요로 한다는 의존 관계를 선언하고,
공통 원천 데이터를 여러 파생 요청이 공유하는 방법을 보여준다. 꽃·개·고양이 이름을
한 번에 만드는 `NamingAllReq`가 원천이고, `NamingReq`가 그중 필요한 필드 하나를
선택해 `NamingData`로 변환한다.

## 파일 구성

- `origin.py`: 꽃·개·고양이 이름을 모두 담은 `NamingAllData` 원천을 정의한다.
- `refer.py`: 원천을 요구하고 `kind`에 맞는 이름 하나만 선택하는 파생 요청을 정의한다.
- `run_ex.py`: 서로 다른 종류와 심볼 집합을 동시에 구독하여 공유 동작을 보여준다.

## 의존 요청 선언

`NamingReq`는 다음과 같이 필요한 원천 요청을 선언한다.

```python
@NamingReq.require(origin.NamingAllReq)
def _(req: NamingReq):
    return origin.NamingAllReq()
```

`Domain`은 `NamingReq` 스테이지를 만들 때 `tr_require`를 확인한다. 필요한
`NamingAllReq` 원천 스테이지를 만들거나 기존 스테이지를 재사용하고, 원천의 출력을
`Receiver`로 파생 binder에 연결한다. 파생 binder는 수신한 `NamingAllData`를
`cast_model()`로 확인한 뒤 `kind`에 해당하는 필드만 `NamingData`로 내보낸다.

```text
NamingAllReq
    -> NamingAllData(flower, dog, cat)
    -> Receiver
    -> NamingReq(kind)
    -> NamingData(name)
```

결과의 `name`에는 변환된 종류를 쉽게 확인할 수 있도록 ` - flower`, ` - dog`,
` - cat` 접미사가 붙는다.

## `content_id`와 스테이지 공유

원천 스테이지는 요청 모델의 `content_id`를 키로 관리되며, 같은 `content_id`에는
하나만 존재한다.

- `NamingAllReq`는 사용자 필드가 없으므로 모든 인스턴스의 `content_id`가 같다.
  따라서 flower·dog·cat 파생 스테이지가 하나의 원천을 공유한다.
- `NamingReq`는 `kind`가 내용에 포함된다. 같은 `kind` 요청은 같은 파생 원천
  스테이지를 공유하고, 다른 `kind` 요청은 별도 파생 스테이지를 사용한다.
- 같은 스테이지를 구독하는 여러 `Stage`의 심볼은 합집합으로 관리된다. 합집합이
  달라지면 현재 binder를 닫고 새 심볼 집합으로 다시 시작한다.

`NamingAllContext.count`와 `NamingContext.count`는 각 binder가 몇 번 다시 시작됐는지
보여준다. 반면 `NamingAllData.count`는 한 번의 원천 binder 실행 안에서 발행된 순번이며,
binder가 재시작되면 다시 1부터 시작한다.

## 실행 시나리오

`run_ex.py`는 여러 요청을 시간차로 시작한다. 요청마다 지정한 개수만큼 데이터를
확인한 뒤 `break`하고, 해당 요청이 사용하던 심볼 구독을 해제한다. 실행 중에는
다음 내용을 로그로 관찰할 수 있다.

- 같은 종류 요청이 파생 컨텍스트를 공유하는지
- 서로 다른 종류 요청이 `NamingAllReq` 원천을 공유하는지
- 구독 심볼의 합집합이 바뀔 때 binder가 다시 시작되는지
- 마지막 구독자가 사라질 때 `detach()`가 호출되는지

## 수명 주기와 주의점

- `NamingAllContext`와 `NamingContext`는 클래스 수준 딕셔너리에 요청을 보관하여
  같은 `content_id`의 컨텍스트가 중복 생성되는지 드러낸다. `@naming.close`에서
  반드시 `detach()`하여 제거한다.
- 파생 binder에는 의존 원천과 연결된 `Receiver`가 필요하다. 연결 없이 실행되면
  예외를 발생시켜 잘못된 구성을 즉시 알린다.
- 원천 binder는 계속 데이터를 발행하므로 소비자는 필요한 시점에 반복을 중단해야 한다.
- 심볼별 라우팅은 `SharedSender`가 담당한다. 원천이 합집합의 데이터를 만들더라도
  각 구독자는 자신이 등록한 심볼의 데이터만 받는다.

## 실행

프로젝트 루트에서 다음 명령을 실행한다.

```bash
uv run python examples/ex02/run_ex.py
```
