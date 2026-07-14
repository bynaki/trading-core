"""요청한 시작값부터 카운트를 생성해 구독 심볼별로 발행하는 예제."""

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
