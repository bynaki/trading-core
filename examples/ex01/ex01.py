"""`Domain.request()`로 소비하는 단순 카운트 원천 제너레이터 예제."""

from asyncio import sleep

from trading_core import (
    DataModel,
    GenerateModel,
    get_model_id,
    initialize,
)


class CountReq(GenerateModel):
    """카운트 스트림의 시작값을 전달하는 요청 모델."""

    start: int


class CountData(DataModel):
    """구독 심볼 하나와 현재 카운트를 담는 출력 모델."""

    count: int


@initialize
def gen01(req: CountReq) -> CountReq:
    """요청 자체를 원천 스테이지의 공유 컨텍스트로 사용한다."""

    return req


@gen01
async def _(req: CountReq, symbols: set[str]):
    """구독 심볼을 순환하며 취소될 때까지 카운트를 발행한다.

    ``finally``는 심볼 변경에 따른 재시작과 마지막 구독 해제 모두에서 실행되는
    업데이트 단위의 정리 지점을 보여준다.
    """

    sym_list = list(symbols)
    start = req.start
    count = start
    try:
        while count:
            remainder = count % len(sym_list)
            yield CountData(symbol=sym_list[remainder], count=count)
            count += 1
            await sleep(1)
    finally:
        print(f"Update 별로 리소스를 정리할 수 있다 - count: {count}")


@gen01.detached
async def _(req: CountReq):
    """마지막 구독이 사라질 때 스테이지 단위 자원을 정리한다."""

    print(f"Detached Stage - {get_model_id(req)}")
    print("Stage 별로 리소스를 정리할 수 있다.")
