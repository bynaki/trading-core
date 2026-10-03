"""콜백이 던질 때의 처리(실패 정책)를 관찰하는 ex10 실행 모듈.

네 시나리오를 차례로 돌린다. 시나리오마다 요청의 `tag`를 달리해 스테이지를 따로 세운다.

1. 원천 generator가 던진다 → 재시도 없이 원천·파생 소비자 모두에게 자기 심볼만 알린다.
   이어서 `update()`로 다시 넣으면 새 스테이지가 init부터 선다.
2. 소비자 `Sender` 하나가 던진다 → 그 Sender만 떼고 공유 generator는 계속 돈다.
3. `detach` 콜백이 던진다 → 정리를 끝까지 하고 ERROR 로그만 남긴다. 호출자에게 안 올라간다.
4. `Domain.stream()` → 실패하면 `StageFailed`를 던지고 끝난다.
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, StageFailed, cast_model
from trading_core.logger import configure, get_logger

if __package__:
    from .ex10 import DETACHES, GEN_STARTS, INITS, TRIPPED, PriceReq, TickData, TickReq, reset
else:
    from ex10 import DETACHES, GEN_STARTS, INITS, TRIPPED, PriceReq, TickData, TickReq, reset

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex10")

WAIT_TIMEOUT = 3.0
"""실패 통지를 기다리는 한도. 회귀가 멈춤으로 나타나지 않게 둔다."""

# (판정 문구, 통과 여부). 시나리오마다 쌓고 끝에 한꺼번에 남긴다.
VERDICTS: list[tuple[str, bool]] = []


def check(what: str, ok: bool) -> None:
    VERDICTS.append((what, ok))


class Consumer:
    """받은 데이터를 세는 `Sender`이자 `on_error` 핸들러.

    `fail_after`를 주면 그 번째 데이터에서 던진다(소비자 쪽 처리 실패).
    """

    def __init__(self, name: str, fail_after: int | None = None) -> None:
        self.name = name
        self.fail_after = fail_after
        self.received = 0
        self.failures: list[StageFailed] = []
        self._failed = asyncio.Event()

    async def __call__(self, data: DataModel) -> None:
        self.received += 1
        log.info(f"수신 {self.name}", symbol=data.symbol)
        if self.fail_after is not None and self.received >= self.fail_after:
            raise ValueError(f"{self.name}가 데이터를 처리하지 못했다")

    async def on_error(self, failed: StageFailed) -> None:
        """코어가 띄운 태스크에서 불린다. 여기서 던져도 코어가 ERROR 로그로 삼킨다."""

        self.failures.append(failed)
        self._failed.set()
        log.warning(
            f"실패 통지 {self.name}",
            symbols=sorted(failed.symbols),
            cause=failed.cause,
            chained=isinstance(failed.__cause__, StageFailed),
        )

    async def wait_failed(self) -> bool:
        try:
            await asyncio.wait_for(self._failed.wait(), WAIT_TIMEOUT)
        except TimeoutError:
            return False
        return True


async def source_failure(domain: Domain) -> None:
    """1. 원천 generator가 던지면 재시도 없이 원천·파생 소비자 모두에게 알린다."""

    log.info("----- 1. 원천 generator가 던진다 -----")
    tag = "ex10.source"
    source_req = TickReq(tag=tag)
    a = Consumer("A")  # 원천을 직접 구독
    b = Consumer("B")  # 같은 원천을 상위로 둔 파생을 구독

    async with (
        domain.subscribe(source_req, a, a.on_error) as sub_a,
        domain.subscribe(PriceReq(tag=tag), b, b.on_error) as sub_b,
    ):
        await sub_a.update({"ETH/USD"})
        await sub_b.update({"BTC"})  # 원천 합집합은 {BTC/USD, ETH/USD}
        await asyncio.sleep(1.2)

        TRIPPED.add(tag)
        notified = await a.wait_failed() and await b.wait_failed()
        check("원천·파생 소비자 모두 실패 통지를 받는다", notified)
        if not notified:
            return
        check(
            "각 소비자는 자기 심볼만 받는다(A: ETH/USD, B: BTC)",
            a.failures[0].symbols == {"ETH/USD"} and b.failures[0].symbols == {"BTC"},
        )
        check(
            "파생 쪽 실패는 상위의 StageFailed로 이어진다(__cause__)",
            isinstance(b.failures[0].__cause__, StageFailed),
        )
        check("실패한 스테이지는 detach까지 정리된다", DETACHES.get(tag) == 1)

        await asyncio.sleep(1.0)  # 재시도가 있다면 이 사이에 init이 다시 불린다
        check("코어는 재시도하지 않는다(init 1회)", INITS.get(tag) == 1)
        check(
            "실패한 심볼은 구독에서 빠진다",
            domain.get_shared_symbols(source_req.tr_content_id) == set(),
        )

        log.info("A가 실패한 심볼을 update()로 다시 넣는다")
        before = a.received
        await sub_a.update(set(a.failures[0].symbols))
        await asyncio.sleep(1.2)
        check(
            "다시 넣으면 새 스테이지가 init부터 선다(init 2회)",
            INITS.get(tag) == 2 and a.received > before,
        )


async def sender_failure(domain: Domain) -> None:
    """2. Sender 하나가 던져도 그 Sender만 떼고 공유 generator는 계속 돈다."""

    log.info("----- 2. 소비자 Sender 하나가 던진다 -----")
    tag = "ex10.sender"
    req = TickReq(tag=tag)
    c = Consumer("C")
    d = Consumer("D", fail_after=3)  # 세 번째 데이터에서 던진다

    async with (
        domain.subscribe(req, c, c.on_error) as sub_c,
        domain.subscribe(req, d, d.on_error) as sub_d,
    ):
        # 같은 심볼이라 D가 빠져도 합집합은 그대로다 → generator가 재시작할 이유가 없다.
        await sub_c.update({"BTC/USD"})
        await sub_d.update({"BTC/USD"})

        notified = await d.wait_failed()
        check("던진 Sender(D)만 실패 통지를 받는다", notified and not c.failures)
        if not notified:
            return
        check(
            "원인은 D 자신의 예외다",
            d.failures[0].cause.startswith("ValueError") and d.failures[0].symbols == {"BTC/USD"},
        )

        before_c, before_d = c.received, d.received
        await asyncio.sleep(1.2)
        check("다른 소비자(C)는 계속 받는다", c.received > before_c)
        check("떼어진 D에는 더 오지 않는다", d.received == before_d)
        check(
            "공유 generator는 재시작하지 않는다",
            INITS.get(tag) == 1 and GEN_STARTS.get(tag) == 1,
        )


async def cleanup_failure(domain: Domain) -> None:
    """3. detach 콜백이 던져도 정리를 끝내고, 호출자에게 올리지 않는다."""

    log.info("----- 3. detach 콜백이 던진다 -----")
    tag = "ex10.cleanup"
    e = Consumer("E")
    raised: Exception | None = None
    try:
        async with domain.subscribe(TickReq(tag=tag, fail_on_detach=True), e, e.on_error) as sub:
            await sub.update({"BTC/USD"})
            await asyncio.sleep(0.8)
        # 여기서 구독이 끊기며 detach 콜백이 던진다. 코어가 ERROR 로그로 남기고 삼킨다.
    except Exception as exc:
        raised = exc
    check("정리 실패가 호출자에게 올라오지 않는다", raised is None)
    check("detach 콜백은 불렸다", DETACHES.get(tag) == 1)
    check("정리 실패는 소비자 실패가 아니다(on_error 없음)", not e.failures)


async def stream_failure(domain: Domain) -> None:
    """4. `stream()`은 실패하면 `StageFailed`를 던지고 끝난다."""

    log.info("----- 4. Domain.stream()이 실패를 만난다 -----")
    tag = "ex10.stream"
    caught: StageFailed | None = None
    try:
        async with asyncio.timeout(WAIT_TIMEOUT + 2):
            async with domain.stream(TickReq(tag=tag), {"BTC/USD"}) as gen:
                async for data in gen:
                    tick = cast_model(data, TickData)
                    log.info("stream 수신", symbol=tick.symbol, seq=tick.seq)
                    if tick.seq == 2:
                        TRIPPED.add(tag)
    except StageFailed as failed:
        caught = failed
        log.warning("stream()이 StageFailed를 던졌다", symbols=sorted(failed.symbols))
    except TimeoutError:
        pass
    check(
        "stream()은 StageFailed를 던지고 끝난다",
        caught is not None and caught.cause.startswith("ConnectionError"),
    )


def log_report() -> None:
    log.info("===== 판정 =====")
    for what, ok in VERDICTS:
        if ok:
            log.info(f"정상: {what}")
        else:
            log.error(f"회귀: {what}")


async def run_ex(domain: Domain) -> None:
    """실패를 주입하며 코어의 실패 정책을 시나리오별로 확인한다."""

    log.info("━━━━━━━━━━ 시작: 콜백이 던질 때의 처리 ━━━━━━━━━━")
    # 판정이 횟수를 보므로 이전 실행의 기록을 비운다.
    VERDICTS.clear()
    reset()
    await source_failure(domain)
    await sender_failure(domain)
    await cleanup_failure(domain)
    await stream_failure(domain)
    log_report()
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex10을 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    try:
        await run_ex(domain)
    finally:
        await domain.stop()


if __name__ == "__main__":
    asyncio.run(main())
