"""합집합이 그대로일 때 재시작이 일어나지 않는지 관찰하는 ex06 실행 모듈.

`Domain.stage()`를 쓰는 이유는 ex05와 같다. 구독을 열어 둔 채 다른 구독을 붙였다
떼야 하고, 재시작 여부를 단계별로 끊어서 재야 하기 때문이다.
"""

import asyncio
from unicodedata import east_asian_width

from trading_core import DataModel, Domain, cast_model

if __package__:
    from .ex06 import GEN_STARTS, QuoteData, QuoteRequest
else:
    from ex06 import GEN_STARTS, QuoteData, QuoteRequest

# 현재 시나리오 단계. `Recorder`가 수신 건수를 이 단계별로 나눠 센다.
PHASE: list[str] = ["0단계"]

PHASE_1 = '1단계: A가 {"BTC"} 구독'
PHASE_2 = '2단계: B가 {"BTC"} 추가 구독 — 합집합 그대로'
PHASE_3 = '3단계: B가 {"BTC", "ETH"}로 교체 — 합집합 확장'
PHASE_4 = "4단계: B 구독 해제 — 합집합 축소"
PHASES = (PHASE_1, PHASE_2, PHASE_3, PHASE_4)

# 단계별 (origin, dependent) 재시작 횟수. `run_ex()`가 단계마다 증가분을 채운다.
STARTS: dict[str, tuple[int, int]] = {}


def set_phase(phase: str) -> None:
    """단계를 바꾸고 구분선을 출력한다."""

    PHASE[0] = phase
    print(f"\n----- {phase} -----")


def snapshot() -> tuple[int, int]:
    """지금까지의 (origin, dependent) generator 시작 횟수를 찍어 둔다."""

    return GEN_STARTS["origin"], GEN_STARTS["dependent"]


def record_starts(phase: str, before: tuple[int, int]) -> None:
    """`before` 이후로 늘어난 시작 횟수를 그 단계의 재시작 횟수로 기록한다."""

    origin, dependent = snapshot()
    STARTS[phase] = (origin - before[0], dependent - before[1])


class Recorder:
    """단계별 수신 건수를 세는 `Sender`."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.counts: dict[str, int] = {phase: 0 for phase in PHASES}

    async def __call__(self, data: DataModel) -> None:
        quote = cast_model(data, QuoteData)
        self.counts[PHASE[0]] = self.counts.get(PHASE[0], 0) + 1
        print(f"  [수신 {self.tag}] {quote.symbol} = {quote.price:,.1f} (seq={quote.seq})")


def _display_width(text: str) -> int:
    """한글처럼 두 칸을 차지하는 글자를 감안한 표시 너비를 센다."""

    return sum(2 if east_asian_width(ch) in "WF" else 1 for ch in text)


def print_report(recorders: list[Recorder]) -> None:
    """단계별 재시작 횟수·수신 건수 표와 판정을 출력한다."""

    print("\n===== 단계별 재시작 횟수와 수신 건수 =====")
    width = max(_display_width(phase) for phase in PHASES)
    headers = ("ORIGIN", "DEP", *(r.tag for r in recorders))
    print(" " * width + "".join(f"  {h:>6}" for h in headers))
    for phase in PHASES:
        pad = " " * (width - _display_width(phase))
        origin, dependent = STARTS[phase]
        cells = (origin, dependent, *(r.counts[phase] for r in recorders))
        print(phase + pad + "".join(f"  {c:>6}" for c in cells))

    a, b = recorders
    print("\n===== 판정 =====")
    if STARTS[PHASE_2] == (0, 0):
        print("정상: 이미 합집합에 있는 심볼로 구독을 붙이면 두 계층 모두 재시작하지 않는다.")
    else:
        print(f"회귀: 합집합이 그대로인데 재시작했다. - {STARTS[PHASE_2]}")
    if b.counts[PHASE_2] > 0:
        print("정상: 재시작 없이도 새 구독자에게 데이터가 간다.")
    else:
        print("회귀: 새 구독자가 데이터를 받지 못한다.")
    if a.counts[PHASE_2] > 0:
        print("정상: 기존 구독자의 스트림이 끊기지 않는다.")
    else:
        print("회귀: 기존 구독자의 스트림이 끊겼다.")
    if STARTS[PHASE_3] == (1, 1) and STARTS[PHASE_4] == (1, 1):
        print("정상: 합집합이 넓어지거나 좁아지면 두 계층이 한 번씩 재시작한다.")
    else:
        print(
            "회귀: 합집합이 바뀌었는데 재시작 횟수가 다르다."
            f" - 3단계 {STARTS[PHASE_3]}, 4단계 {STARTS[PHASE_4]}"
        )


async def run_ex(domain: Domain) -> None:
    """구독을 붙였다 떼며 합집합 변화와 재시작 횟수의 관계를 관찰한다."""

    print("===== runing ex06 =====")
    req = QuoteRequest(market="spot")
    recorder_a = Recorder("A")
    recorder_b = Recorder("B")

    # 같은 요청(=같은 content_id)이므로 두 구독자는 하나의 파생 스테이지를 공유한다.
    async with domain.stage(req, recorder_a) as stage_a:
        before = snapshot()
        set_phase(PHASE_1)
        await stage_a.update({"BTC"})
        await asyncio.sleep(2)
        record_starts(PHASE_1, before)

        async with domain.stage(req, recorder_b) as stage_b:
            # A가 이미 구독 중인 심볼이다. 합집합은 {"BTC"} 그대로라 재시작이 없어야 한다.
            before = snapshot()
            set_phase(PHASE_2)
            await stage_b.update({"BTC"})
            await asyncio.sleep(2)
            record_starts(PHASE_2, before)

            # 여기서는 합집합이 {"BTC", "ETH"}로 넓어지므로 재시작해야 한다.
            before = snapshot()
            set_phase(PHASE_3)
            await stage_b.update({"BTC", "ETH"})
            await asyncio.sleep(2)
            record_starts(PHASE_3, before)

            # 빈 집합은 구독 해제다. 합집합이 {"BTC"}로 좁아지므로 역시 재시작한다.
            before = snapshot()
            set_phase(PHASE_4)
            await stage_b.update(set())
            await asyncio.sleep(2)
            record_starts(PHASE_4, before)

    print_report([recorder_a, recorder_b])
    print("\n===== finished ex06 =====")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex06을 실행한다."""

    domain = Domain()
    await domain.start()
    try:
        await run_ex(domain)
    finally:
        await domain.stop()


if __name__ == "__main__":
    asyncio.run(main())
