"""독립 원천 제너레이터의 기본 사용법을 보여주는 예제.

``CountReq``와 ``CountModel``로 요청·응답 모델을 정의하고,
``@generator``로 요청 모델에 제너레이터를 등록한다. 다른 요청의 데이터를
입력받지 않는 원천 제너레이터이므로 binder의 ``recv``는 사용하지 않는다.

호출자는 ``Domain.request()``가 반환한 비동기 스트림을 소비한다. 제너레이터는
요청한 시작값의 다음 수부터 10까지 카운트를 만들고, 구독한 심볼을 순환하며
각 결과에 하나씩 배정한다. 스트림이 정상 종료되거나 조기에 닫혀도
``finally``에서 자원 정리 로직이 실행되는 것도 함께 보여준다.

심볼은 집합으로 전달되므로 발행 순서는 보장되지 않는다. 이 예제는 하나 이상의
심볼과 10보다 작은 시작값이 전달된다고 가정한다.
"""

from asyncio import sleep

from trading_core import (
    DataModel,
    RequestModel,
    generator,
)
from trading_core.model import Receiver


class CountReq(RequestModel):
    """제너레이터를 시작할 때 전달하는 요청 모델."""

    start: int


class CountModel(DataModel):
    """제너레이터가 구독자에게 한 건씩 내보내는 데이터 모델."""

    count: int


@generator(CountReq)
def gen01(req: CountReq) -> CountReq:
    """CountReq를 제너레이터에 등록하고 요청 자체를 실행 컨텍스트로 반환한다."""

    return req


@gen01.bind
async def _(req: CountReq, symbols: set[str], recv: Receiver | None):
    """구독 심볼을 순환하며 1초마다 다음 카운트 값을 생성한다.

    정상 종료되거나 취소·예외로 닫혀도 ``finally``에서 정리 로직을 실행한다.
    """

    sym_list = list(symbols)
    count = req.start
    try:
        while True:
            count += 1
            remainder = count % len(sym_list)
            yield CountModel(symbol=sym_list[remainder], count=count)
            await sleep(1)
            if count == 10:
                break
    finally:
        print(f"Must resource cleaned up - count: {count}")
