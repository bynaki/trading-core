"""`Domain.stage()`의 동적 심볼 갱신을 보여주는 가격 스트림 예제."""

import random
from asyncio import sleep
from collections.abc import Set
from typing import Literal

from trading_core import DataModel, GenerateModel, initialize


class PriceReq(GenerateModel):
    """가격 증가 단위를 결정할 OHLC 종류를 지정하는 요청."""

    ohlc: Literal["open", "high", "low", "close"]


class PriceData(DataModel):
    """선택된 심볼과 컨텍스트가 계산한 누적 가격."""

    price: int


class PriceContext:
    """binder 재시작 사이에도 심볼별 발행 횟수를 유지하는 공유 상태."""

    def __init__(self, quantity: int) -> None:
        self._quantity = quantity
        self._count_dict: dict[str, int] = {}
        self.updating_count = 0

    def price(self, symbol: str) -> int:
        """심볼의 호출 횟수에 요청별 증가 단위를 곱한 가격을 반환한다."""

        if not self._count_dict.get(symbol):
            self._count_dict[symbol] = 0
        self._count_dict[symbol] += 1
        return self._count_dict[symbol] * self._quantity


@initialize
def price(req: PriceReq):
    """OHLC 종류를 가격 증가 단위로 바꾸어 스테이지 컨텍스트를 만든다."""

    quantity = 0
    if req.ohlc == "open":
        quantity = 10
    elif req.ohlc == "high":
        quantity = 1000
    elif req.ohlc == "low":
        quantity = 1
    elif req.ohlc == "close":
        quantity = 100
    return PriceContext(quantity)


@price
async def _(ctx: PriceContext, symbols: Set[str]):
    """현재 구독 심볼 중 하나를 무작위로 골라 가격을 계속 발행한다."""

    ctx.updating_count += 1
    print(f"!!!!!!!! {ctx.updating_count} Updating Stage")
    try:
        while True:
            symbol = random.choice(tuple(symbols))
            yield PriceData(symbol=symbol, price=ctx.price(symbol))
            await sleep(1)
    finally:
        print("Update 별로 자원을 정리할 수 있다.")


@price.detached
async def _(ctx: PriceContext):
    """마지막 구독이 사라질 때 원천 스테이지 종료를 알린다."""

    print("******* Detached Stage")
