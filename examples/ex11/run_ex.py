"""init 콜백이 던질 때의 처리를 관찰하는 ex11 실행 모듈.

다섯 시나리오를 차례로 돌린다. 시나리오마다 계정·이름을 달리해 스테이지를 따로 세운다.

1. 원천 init이 던진다 → `update()`는 던지지 않고, 스테이지 없이 요청 심볼의 실패를 알린다.
   다시 넣으면 init부터 다시 한다.
2. 파생의 상위(원천) init이 던진다 → 상위 스테이지가 실패한 것처럼 파생까지 연쇄한다. 파생
   generator는 시작하지 않는다.
3. 세션 자신의 init이 던진다 → `subscribe()`는 init을 부르지 않는다. 첫 `update()`가 init하고,
   실패는 그 `update()`가 돌아올 때 이미 알려져 있다.
4. 세션 슬롯의 상위 init이 던진다 → 그 상위를 쓰는 심볼 하나만 실패하고 나머지는 계속 받는다.
5. binder가 없는 요청 → init 실패가 아니라 등록 오류다. `DomainError`가 호출자에게 그대로 간다.
"""

import asyncio
from pathlib import Path

from trading_core import DataModel, Domain, DomainError, StageFailed
from trading_core.logger import configure, get_logger

if __package__:
    from .ex11 import (
        DETACHES,
        GEN_STARTS,
        INITS,
        REFUSED,
        UNBOUND,
        PriceReq,
        TickReq,
        UnboundReq,
        WatchReq,
        reset,
        watch_account,
    )
else:
    from ex11 import (
        DETACHES,
        GEN_STARTS,
        INITS,
        REFUSED,
        UNBOUND,
        PriceReq,
        TickReq,
        UnboundReq,
        WatchReq,
        reset,
        watch_account,
    )

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex11")

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
        self._failed = asyncio.Event()

    async def __call__(self, data: DataModel) -> None:
        self.received[data.symbol] = self.received.get(data.symbol, 0) + 1
        log.info(f"수신 {self.name}", symbol=data.symbol)

    async def on_error(self, failed: StageFailed) -> None:
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

    async def wait_received(self, symbol: str) -> bool:
        """`symbol`을 한 건이라도 받을 때까지 기다린다."""

        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not self.received.get(symbol):
                    await asyncio.sleep(0.05)
        except TimeoutError:
            return False
        return True


async def update_quietly(sub, symbols: set[str]) -> Exception | None:
    """`sub.update()`가 던지면 그 예외를, 아니면 `None`을 돌려준다."""

    try:
        await sub.update(symbols)
    except Exception as exc:
        return exc
    return None


async def source_init_failure(domain: Domain) -> None:
    """1. 원천 init이 던지면 스테이지 없이 요청 심볼의 실패를 알린다."""

    log.info("----- 1. 원천 init이 던진다 -----")
    account = "ex11.source"
    req = TickReq(account=account)
    a = Consumer("A")

    async with domain.subscribe(req, a, a.on_error) as sub:
        REFUSED.add(account)
        raised = await update_quietly(sub, {"BTC/USD", "ETH/USD"})
        check("update()는 init 실패를 던지지 않는다", raised is None)

        notified = await a.wait_failed()
        check("요청한 심볼 모두의 실패를 알린다", notified)
        if not notified:
            return
        failed = a.failures[0]
        check(
            "원인은 init이 던진 예외다",
            failed.symbols == {"BTC/USD", "ETH/USD"} and failed.cause.startswith("PermissionError"),
        )
        check(
            "스테이지가 서지 않는다(공유 심볼·generator·detach 없음)",
            domain.get_shared_symbols(req.tr_content_id) == set()
            and GEN_STARTS.get(f"tick:{account}", 0) == 0
            and DETACHES.get(f"tick:{account}", 0) == 0,
        )

        log.info("A가 실패한 심볼을 update()로 다시 넣는다")
        await sub.update(set(failed.symbols))
        check(
            "다시 넣으면 init부터 다시 한다(로그인 2회차)",
            await a.wait_received("BTC/USD") and INITS.get(f"tick:{account}") == 2,
        )


async def derived_upstream_init_failure(domain: Domain) -> None:
    """2. 파생의 상위 init이 던지면 상위 실패처럼 파생까지 연쇄한다."""

    log.info("----- 2. 파생의 상위(원천) init이 던진다 -----")
    account = "ex11.derived"
    req = PriceReq(account=account)
    b = Consumer("B")

    async with domain.subscribe(req, b, b.on_error) as sub:
        REFUSED.add(account)  # 파생이 아니라 상위 원천의 계정이다
        raised = await update_quietly(sub, {"BTC"})
        check("update()는 상위 init 실패도 던지지 않는다", raised is None)

        notified = await b.wait_failed()
        check("파생 소비자가 실패 통지를 받는다", notified)
        if not notified:
            return
        failed = b.failures[0]
        upstream_failed = failed.__cause__
        check(
            "파생 소비자는 자기 하위 표기 심볼(BTC)로 받는다",
            failed.content_id == req.tr_content_id and failed.symbols == {"BTC"},
        )
        check(
            "__cause__는 상위의 StageFailed(BTC/USD)다",
            isinstance(upstream_failed, StageFailed)
            and upstream_failed.content_id == TickReq(account=account).tr_content_id
            and upstream_failed.symbols == {"BTC/USD"},
        )
        check(
            "파생 generator는 시작하지 않고, 파생 컨텍스트는 detach된다",
            GEN_STARTS.get(f"price:{account}", 0) == 0 and DETACHES.get(f"price:{account}") == 1,
        )
        check(
            "파생 스테이지에 심볼이 남지 않는다",
            domain.get_shared_symbols(req.tr_content_id) == set(),
        )

        log.info("B가 다시 넣는다")
        await sub.update({"BTC"})
        check("다시 넣으면 상위부터 다시 선다", await b.wait_received("BTC"))


async def session_init_failure(domain: Domain) -> None:
    """3. 세션 init은 첫 `update()`에서 한다. 실패는 그 `update()`가 돌아올 때 이미 알려져 있다."""

    log.info("----- 3. 세션 자신의 init이 던진다 -----")
    name = "ex11.session"
    c = Consumer("C")
    REFUSED.add(name)

    async with domain.subscribe(WatchReq(name=name), c, c.on_error) as sub:
        check("subscribe()는 init을 부르지 않는다", INITS.get(f"watch:{name}", 0) == 0)

        raised = await update_quietly(sub, {"BTC"})
        check("update()는 세션 init 실패를 던지지 않는다", raised is None)
        check(
            "update()가 돌아올 때 이미 알렸다(기다리지 않음)",
            len(c.failures) == 1 and c.failures[0].symbols == {"BTC"},
        )

        log.info("C가 다시 넣는다")
        await sub.update({"BTC"})
        check(
            "다음 update()가 init을 다시 한다(세션 init 2회차)",
            await c.wait_received("BTC") and INITS.get(f"watch:{name}") == 2,
        )


async def session_upstream_init_failure(domain: Domain) -> None:
    """4. 세션 슬롯의 상위 init이 던지면 그 상위를 쓰는 심볼만 실패한다."""

    log.info("----- 4. 세션 슬롯의 상위 init이 던진다 -----")
    name = "ex11.slot"
    d = Consumer("D")

    async with domain.subscribe(WatchReq(name=name), d, d.on_error) as sub:
        REFUSED.add(watch_account(name, "ETH"))  # ETH 슬롯이 붙는 원천의 계정만 거부한다
        raised = await update_quietly(sub, {"BTC", "ETH"})
        check("update()는 슬롯 상위 init 실패를 던지지 않는다", raised is None)

        notified = await d.wait_failed()
        check("ETH만 실패 통지를 받는다(하위 표기)", notified and d.failures[0].symbols == {"ETH"})
        if not notified:
            return
        check("bind된 ETH 슬롯은 unbind로 짝을 맞춘다", UNBOUND.get(f"watch:{name}") == ["ETH"])

        before = d.received.get("BTC", 0)
        await asyncio.sleep(1.2)
        check("BTC는 계속 받는다", d.received.get("BTC", 0) > before)

        log.info("D가 ETH를 다시 넣는다")
        await sub.update({"BTC", "ETH"})
        check("다시 넣은 ETH도 받는다", await d.wait_received("ETH"))


async def registration_error(domain: Domain) -> None:
    """5. binder가 없는 요청은 init 실패가 아니다. `DomainError`가 호출자에게 그대로 간다."""

    log.info("----- 5. binder가 없는 요청(등록 오류) -----")
    e = Consumer("E")
    raised: Exception | None = None
    try:
        async with domain.subscribe(UnboundReq(), e, e.on_error) as sub:
            await sub.update({"BTC/USD"})
    except DomainError as exc:
        raised = exc
        log.warning("subscribe()가 DomainError를 던졌다", error=str(exc))
    check("등록 오류는 DomainError로 호출자에게 간다", raised is not None)
    check("등록 오류는 on_error로 오지 않는다", not e.failures)


def log_report() -> None:
    log.info("===== 판정 =====")
    for what, ok in VERDICTS:
        if ok:
            log.info(f"정상: {what}")
        else:
            log.error(f"회귀: {what}")


async def run_ex(domain: Domain) -> None:
    """init을 실패시키며 코어의 처리를 시나리오별로 확인한다."""

    log.info("━━━━━━━━━━ 시작: init 콜백이 던질 때의 처리 ━━━━━━━━━━")
    # 판정이 횟수를 보므로 이전 실행의 기록을 비운다.
    VERDICTS.clear()
    reset()
    for scenario in (
        source_init_failure,
        derived_upstream_init_failure,
        session_init_failure,
        session_upstream_init_failure,
        registration_error,
    ):
        # 이 예제가 보이려는 것이 "던지지 않는다"이므로, 새어 나온 예외도 회귀로 남긴다.
        try:
            await scenario(domain)
        except Exception:
            log.exception("시나리오가 예외로 끝났다", scenario=scenario.__name__)
            check(f"{scenario.__name__}가 예외 없이 끝난다", False)
    log_report()
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex11을 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    try:
        await run_ex(domain)
    finally:
        await domain.stop()


if __name__ == "__main__":
    asyncio.run(main())
