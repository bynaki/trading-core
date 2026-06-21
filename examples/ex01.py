"""아주 간단한 사용법.

task(작업 단위)와 domain(요청 진입점)을 정의하는 최소 예제.

- task   : 입력 DataModel 타입별로 핸들러를 등록하고, model_id로 디스패치한다.
- domain : RequestModel 타입을 받아 symbol에 묶인 Sequence를 흘려보낸다.
"""

from trading_core import (
    task,
    DataModel,
    RequestModel,
    domain,
    DomainContext,
)


class TaskContext:
    """task가 호출 사이에 들고 다니는 상태(context). 여기서는 누적 합을 보관한다."""

    def __init__(self):
        self.sum = 0


class CountModel(DataModel):
    """task로 흘러드는 입력 데이터.

    DataModel을 상속하면 symbol 등 메타데이터가 함께 따라온다.
    """

    count: int


@task(TaskContext)
def task01():
    """작업 단위를 선언한다.

    이 함수는 context를 초기화하는 콜백이며, task가 처음 실행될 때 한 번 호출된다.
    """
    return TaskContext()


@task01.on(CountModel)
async def _(ctx: TaskContext, data: CountModel):
    """CountModel이 들어오면 실행될 핸들러.

    ctx에는 task01이 만든 TaskContext가, data에는 들어온 CountModel이 전달된다.
    """
    ctx.sum += data.count
    print(f"symbol: {data.symbol}, count: {data.count}, sum: {ctx.sum}")


class CountReq(RequestModel):
    """domain의 진입점이 되는 요청 모델. 호출 시 필요한 파라미터를 필드로 둔다."""

    start: int = 0


@domain(CountReq)
def domain01(req: CountReq):
    """CountReq를 처리하는 domain을 전역 레지스트리에 등록한다.

    이 함수는 요청(req)을 받아 domain의 context를 만들어 반환한다.
    """
    return DomainContext(req)


@domain01.on
async def _(ctx: DomainContext[CountReq], symbol: str):
    """요청이 들어왔을 때 흘려보낼 Sequence를 정의하는 비동기 제너레이터.

    ctx.req_model(symbol)은 그 symbol에 묶인 Sequence를 만든다. yield로 하나씩 내보낸다.
    """
    yield ctx.req_model(symbol)
