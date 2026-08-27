"""두 소비자가 같은 파생 요청을 서로 다른 심볼로 동시에 구독하는 ex05 실행 모듈.

`Domain.request()` 대신 저수준 `Domain.stage()`를 쓴다. 구독을 열어 둔 채 다른
구독을 붙였다 떼는 시나리오를 그대로 표현할 수 있고, 데이터가 오지 않는 구독자도
블로킹 없이 관찰할 수 있기 때문이다.
"""

import asyncio
from unicodedata import east_asian_width

from trading_core import DataModel, Domain, cast_model

if __package__:
    from .ex05 import PriceData, PriceRequest
else:
    from ex05 import PriceData, PriceRequest

# 현재 시나리오 단계. `Recorder`가 수신 건수를 이 단계별로 나눠 센다.
PHASE: list[str] = ["0단계"]

PHASE_1 = '1단계: A가 {"BTC"} 단독 구독'
PHASE_2 = '2단계: A{"BTC"} + B{"ETH"} 동시 구독'
PHASE_3 = "3단계: B 구독 해제, A만 남음"
PHASES = (PHASE_1, PHASE_2, PHASE_3)


def set_phase(phase: str) -> None:
    """단계를 바꾸고 구분선을 출력한다."""

    PHASE[0] = phase
    print(f"\n----- {phase} -----")


class Recorder:
    """단계별 수신 건수를 세는 `Sender`.

    `Domain.stage()`에 넘기면 파생 스테이지의 `SendRouter`가 이 인스턴스를 구독자로
    등록하고, 구독한 심볼의 데이터만 fan-out한다.
    """

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.counts: dict[str, int] = {phase: 0 for phase in PHASES}

    async def __call__(self, data: DataModel) -> None:
        price = cast_model(data, PriceData)
        self.counts[PHASE[0]] = self.counts.get(PHASE[0], 0) + 1
        print(f"  [수신 {self.tag}] {price.symbol} = {price.price:,.1f} (seq={price.seq})")


def _display_width(text: str) -> int:
    """한글처럼 두 칸을 차지하는 글자를 감안한 표시 너비를 센다."""

    return sum(2 if east_asian_width(ch) in "WF" else 1 for ch in text)


def print_report(recorders: list[Recorder]) -> None:
    """단계별 수신 건수 표와 판정을 출력한다."""

    print("\n===== 단계별 수신 건수 =====")
    width = max(_display_width(phase) for phase in PHASES)
    print(" " * width + "".join(f"  {r.tag:>6}" for r in recorders))
    for phase in PHASES:
        pad = " " * (width - _display_width(phase))
        print(phase + pad + "".join(f"  {r.counts[phase]:>6}" for r in recorders))

    a, _ = recorders
    print("\n===== 판정 =====")
    if a.counts[PHASE_2] == 0:
        print("회귀: B가 붙는 순간 A가 데이터를 전혀 받지 못한다.")
    else:
        print("정상: A는 B가 붙은 뒤에도 계속 데이터를 받는다.")
    if a.counts[PHASE_3] == 0:
        print("회귀: B가 떠난 뒤에도 A의 상위 구독이 돌아오지 않는다.")
    else:
        print("정상: B가 떠난 뒤 A의 상위 구독이 남아 있다.")


async def run_ex(domain: Domain) -> None:
    """A·B 두 구독자를 시간차로 붙였다 떼며 상위 구독이 어떻게 바뀌는지 관찰한다."""

    print("===== runing ex05 =====")
    req = PriceRequest(quote="usd")
    recorder_a = Recorder("A")
    recorder_b = Recorder("B")

    # 같은 요청(=같은 content_id)이므로 두 구독자는 하나의 파생 스테이지를 공유한다.
    async with domain.stage(req, recorder_a) as stage_a:
        set_phase(PHASE_1)
        await stage_a.update({"BTC"})
        await asyncio.sleep(2)

        async with domain.stage(req, recorder_b) as stage_b:
            set_phase(PHASE_2)
            await stage_b.update({"ETH"})
            await asyncio.sleep(3)

        set_phase(PHASE_3)
        await asyncio.sleep(2)

    print_report([recorder_a, recorder_b])
    print("\n===== finished ex05 =====")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex05를 실행한다."""

    domain = Domain()
    await domain.start()
    try:
        await run_ex(domain)
    finally:
        await domain.stop()


if __name__ == "__main__":
    asyncio.run(main())
