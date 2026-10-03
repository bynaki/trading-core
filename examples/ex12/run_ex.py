"""binder가 심볼 하나만 거부할 때의 처리를 관찰하는 ex12 실행 모듈.

네 시나리오를 차례로 돌린다. 시나리오마다 계정을 달리해 스테이지를 따로 세운다.

1. 원천이 도는 중에 심볼 하나를 상장 폐지로 거부한다 → 그 심볼을 구독한 소비자들만 그 심볼의
   실패를 받고, 원천은 남은 심볼로 다시 돈다. 다시 넣어도 binder가 또 거부한다.
2. 오타 심볼로 구독한다 → 원천이 시작하자마자 그 심볼만 거부한다.
3. 파생의 상위가 심볼을 거부한다 → 파생 소비자는 대응하는 하위 심볼만 실패로 받는다.
4. 세션 슬롯이 붙은 상위가 심볼을 거부한다 → 그 슬롯만 닫히고 unbind된다.
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, StageFailed, SymbolRejected
from trading_core.logger import configure, get_logger

if __package__:
    from .ex12 import DETACHES, GEN_STARTS, UNBOUND, PriceReq, TickReq, WatchReq, delist, reset
else:
    from ex12 import DETACHES, GEN_STARTS, UNBOUND, PriceReq, TickReq, WatchReq, delist, reset

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex12")

WAIT_TIMEOUT = 3.0
"""실패 통지·수신을 기다리는 한도. 회귀가 멈춤으로 나타나지 않게 둔다."""

# (판정 문구, 통과 여부). 시나리오마다 쌓고 끝에 한꺼번에 남긴다.
VERDICTS: list[tuple[str, bool]] = []


def check(what: str, ok: bool) -> None:
    VERDICTS.append((what, ok))


class Consumer:
    """받은 데이터를 심볼별로 세는 `Sender`이자 `on_error` 핸들러."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.received: dict[str, int] = {}
        self.failures: list[StageFailed] = []

    async def __call__(self, data: DataModel) -> None:
        self.received[data.symbol] = self.received.get(data.symbol, 0) + 1
        log.info(f"수신 {self.name}", symbol=data.symbol)

    async def on_error(self, failed: StageFailed) -> None:
        self.failures.append(failed)
        log.warning(
            f"실패 통지 {self.name}",
            symbols=sorted(failed.symbols),
            cause=failed.cause,
            chained=isinstance(failed.__cause__, StageFailed),
        )

    async def wait_failed(self, count: int = 1) -> bool:
        """실패 통지가 `count`건 올 때까지 기다린다."""

        return await _wait(lambda: len(self.failures) >= count)

    async def wait_received(self, symbol: str) -> bool:
        """지금부터 `symbol`을 한 건이라도 새로 받을 때까지 기다린다."""

        before = self.received.get(symbol, 0)
        return await _wait(lambda: self.received.get(symbol, 0) > before)


async def _wait(predicate) -> bool:
    try:
        async with asyncio.timeout(WAIT_TIMEOUT):
            while not predicate():
                await asyncio.sleep(0.05)
    except TimeoutError:
        return False
    return True


def rejected_cause(failed: StageFailed) -> SymbolRejected | None:
    """`__cause__`를 따라가 binder가 던진 `SymbolRejected`를 찾는다."""

    cause = failed.__cause__
    while isinstance(cause, StageFailed):
        cause = cause.__cause__
    return cause if isinstance(cause, SymbolRejected) else None


async def delisting_source(domain: Domain) -> None:
    """1. 원천이 도는 중에 심볼 하나를 거부하면 그 심볼만 실패한다."""

    log.info("----- 1. 원천이 상장 폐지된 심볼을 거부한다 -----")
    account = "ex12.source"
    req = TickReq(account=account)
    a, b = Consumer("A"), Consumer("B")

    async with (
        domain.subscribe(req, a, a.on_error) as sub_a,
        domain.subscribe(req, b, b.on_error) as sub_b,
    ):
        await sub_a.update({"BTC/USD", "DOGE/USD"})
        await sub_b.update({"DOGE/USD", "ETH/USD"})
        await a.wait_received("DOGE/USD")

        log.info("거래소가 DOGE/USD를 상장 폐지한다")
        delist(account, "DOGE/USD")
        notified = await a.wait_failed() and await b.wait_failed()
        check("DOGE/USD를 구독한 A·B가 실패 통지를 받는다", notified)
        if not notified:
            return
        check(
            "각자 DOGE/USD만 받는다(다른 심볼은 실패가 아니다)",
            a.failures[0].symbols == {"DOGE/USD"} and b.failures[0].symbols == {"DOGE/USD"},
        )
        rejected = rejected_cause(a.failures[0])
        check(
            "원인은 binder가 던진 SymbolRejected(상장 폐지)다",
            rejected is not None and rejected.reason == "상장 폐지",
        )
        check(
            "스테이지는 내려가지 않고 남은 심볼로 다시 돈다",
            domain.get_shared_symbols(req.tr_content_id) == {"BTC/USD", "ETH/USD"}
            and await _wait(lambda: GEN_STARTS[f"tick:{account}"][-1] == ["BTC/USD", "ETH/USD"])
            and DETACHES.get(f"tick:{account}", 0) == 0,
        )
        check(
            "A는 BTC/USD, B는 ETH/USD를 계속 받는다",
            await a.wait_received("BTC/USD") and await b.wait_received("ETH/USD"),
        )

        log.info("A가 DOGE/USD를 다시 넣는다")
        await sub_a.update({"BTC/USD", "DOGE/USD"})
        check(
            "다시 넣어도 binder가 또 거부한다(다시 넣을지는 소비자, 줄지는 binder가 정한다)",
            await a.wait_failed(2) and a.failures[1].symbols == {"DOGE/USD"},
        )


async def unknown_symbol(domain: Domain) -> None:
    """2. 오타 심볼은 원천이 시작하자마자 거부한다."""

    log.info("----- 2. 오타 심볼로 구독한다 -----")
    account = "ex12.typo"
    req = TickReq(account=account)
    c = Consumer("C")

    async with domain.subscribe(req, c, c.on_error) as sub:
        await sub.update({"BTC/USD", "BTCC/USD"})
        notified = await c.wait_failed()
        check("오타 심볼(BTCC/USD)만 실패 통지를 받는다", notified)
        if not notified:
            return
        rejected = rejected_cause(c.failures[0])
        check(
            "원인은 '거래소에 없는 심볼'이다",
            c.failures[0].symbols == {"BTCC/USD"}
            and rejected is not None
            and rejected.reason == "거래소에 없는 심볼",
        )
        check("같이 넣은 BTC/USD는 받는다", await c.wait_received("BTC/USD"))


async def derived_upstream_rejection(domain: Domain) -> None:
    """3. 파생의 상위가 심볼을 거부하면 대응하는 하위 심볼만 실패한다."""

    log.info("----- 3. 파생의 상위가 심볼을 거부한다 -----")
    account = "ex12.derived"
    req = PriceReq(account=account)
    d = Consumer("D")

    async with domain.subscribe(req, d, d.on_error) as sub:
        await sub.update({"BTC", "DOGE"})
        await d.wait_received("DOGE")

        log.info("거래소가 DOGE/USD를 상장 폐지한다")
        delist(account, "DOGE/USD")
        notified = await d.wait_failed()
        check("파생 소비자가 실패 통지를 받는다", notified)
        if not notified:
            return
        failed = d.failures[0]
        upstream_failed = failed.__cause__
        check(
            "하위 표기 DOGE만 받고, __cause__는 상위의 StageFailed(DOGE/USD)다",
            failed.symbols == {"DOGE"}
            and isinstance(upstream_failed, StageFailed)
            and upstream_failed.symbols == {"DOGE/USD"}
            and rejected_cause(failed) is not None,
        )
        check(
            "파생은 남은 BTC로 다시 돌고 계속 받는다",
            await _wait(lambda: GEN_STARTS[f"price:{account}"][-1] == ["BTC"])
            and await d.wait_received("BTC"),
        )


async def session_upstream_rejection(domain: Domain) -> None:
    """4. 세션 슬롯이 붙은 상위가 심볼을 거부하면 그 슬롯만 닫힌다."""

    log.info("----- 4. 세션 슬롯이 붙은 상위가 심볼을 거부한다 -----")
    account = "ex12.session"
    e = Consumer("E")

    async with domain.subscribe(WatchReq(account=account), e, e.on_error) as sub:
        await sub.update({"BTC", "DOGE"})
        await e.wait_received("DOGE")

        log.info("거래소가 DOGE/USD를 상장 폐지한다")
        delist(account, "DOGE/USD")
        notified = await e.wait_failed()
        check(
            "DOGE만 실패 통지를 받는다(하위 표기)", notified and e.failures[0].symbols == {"DOGE"}
        )
        if not notified:
            return
        check(
            "bind된 DOGE 슬롯은 unbind로 짝을 맞춘다", UNBOUND.get(f"watch:{account}") == ["DOGE"]
        )
        check("BTC는 계속 받는다", await e.wait_received("BTC"))


def log_report() -> None:
    log.info("===== 판정 =====")
    for what, ok in VERDICTS:
        if ok:
            log.info(f"정상: {what}")
        else:
            log.error(f"회귀: {what}")


async def run_ex(domain: Domain) -> None:
    """binder가 심볼을 거부하게 하며 코어의 처리를 시나리오별로 확인한다."""

    log.info("━━━━━━━━━━ 시작: binder가 심볼 하나를 거부할 때의 처리 ━━━━━━━━━━")
    # 판정이 기록을 보므로 이전 실행의 기록을 비운다.
    VERDICTS.clear()
    reset()
    for scenario in (
        delisting_source,
        unknown_symbol,
        derived_upstream_rejection,
        session_upstream_rejection,
    ):
        try:
            await scenario(domain)
        except Exception:
            log.exception("시나리오가 예외로 끝났다", scenario=scenario.__name__)
            check(f"{scenario.__name__}가 예외 없이 끝난다", False)
    log_report()
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex12를 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    try:
        await run_ex(domain)
    finally:
        await domain.stop()


if __name__ == "__main__":
    asyncio.run(main())
