"""ex08을 실제 `Domain`에서 실행하는 모듈.

내용이 완전히 같은 `WatchReq(quote="USD")` 두 개를 만들어 **같은 심볼** `{"BTC"}`로
동시에 구독한다. content_id가 같으니 원천이라면 스테이지 하나를 공유했겠지만,
요청형(instanter)은 요청마다 스테이지와 컨텍스트를 따로 만든다.
"""

import asyncio
from pathlib import Path

from trading_core import Domain, cast_model
from trading_core.logger import configure, get_logger

if __package__:
    from .ex08 import BeatReq, WatchData, WatchReq
else:
    from ex08 import BeatReq, WatchData, WatchReq

SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 직접 실행할 때 `main()`이 읽는다."""

log = get_logger("ex08")

TAKE = 3
"""소비자 하나가 받고 끝낼 데이터 수."""


def report_registry(domain: Domain, req: WatchReq) -> None:
    """공유 레지스트리(`_origin_stage_dict`)에 무엇이 들어 있는지 남긴다.

    원천 `BeatReq`는 등록되어 있고, 요청형 `WatchReq`는 등록되어 있지 않다.
    `_define_inst_stage()`가 이 레지스트리를 아예 건드리지 않기 때문이다.
    """

    beat_stage = domain.get_origin_stage(BeatReq().get_tr_content_id())
    log.info(
        "----- 원천 `BeatReq` 스테이지: 공유됨 -----",
        upper=sorted(beat_stage.output.symbols),
    )
    try:
        domain.get_origin_stage(req.get_tr_content_id())
    except KeyError:
        log.info("----- 요청형 `WatchReq` 스테이지: 공유 레지스트리에 없음 -----")


async def consume(name: str, domain: Domain, req: WatchReq, probe: bool) -> None:
    """`req`를 `{"BTC"}`로 구독해 `TAKE`건을 받고 끝낸다.

    `probe`가 참인 소비자만 첫 데이터를 받은 뒤 레지스트리를 한 번 들여다본다.
    """

    received = 0
    async with domain.request(req, {"BTC"}) as gen:
        async for data in gen:
            d = cast_model(data, WatchData)
            log.info(f"수신 {name}", ctx=d.ctx_no, seen=d.seen, symbol=d.symbol, price=d.price)
            received += 1
            if probe and received == 1:
                report_registry(domain, req)
            if received == TAKE:
                break


async def run_ex(domain: Domain) -> None:
    """내용이 같은 요청 두 개를 같은 심볼로 동시에 구독한다."""

    log.info("━━━━━━━━━━ 시작: 같은 content_id라도 RequestModel은 공유되지 않는다 ━━━━━━━━━━")
    req_a = WatchReq(quote="USD")
    req_b = WatchReq(quote="USD")
    log.info(
        "content_id가 같은가",
        same=req_a.get_tr_content_id() == req_b.get_tr_content_id(),
    )
    async with asyncio.TaskGroup() as tg:
        tg.create_task(consume("A", domain, req_a, probe=True))
        tg.create_task(consume("B", domain, req_b, probe=False))
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex08을 실행한다."""

    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
