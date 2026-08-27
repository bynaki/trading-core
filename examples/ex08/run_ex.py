"""ex08을 실제 `Domain`에서 실행하는 모듈.

내용이 완전히 같은 `WatchReq(quote="USD")` 두 개를 만들어 **같은 심볼** `{"BTC"}`로
동시에 구독한다. content_id가 같으니 원천이라면 스테이지 하나를 공유했겠지만,
요청형(instanter)은 요청마다 스테이지와 컨텍스트를 따로 만든다.
"""

import asyncio

from trading_core import Domain, cast_model

if __package__:
    from .ex08 import BeatReq, WatchData, WatchReq
else:
    from ex08 import BeatReq, WatchData, WatchReq

TAKE = 3
"""소비자 하나가 받고 끝낼 데이터 수."""


def report_registry(domain: Domain, req: WatchReq) -> None:
    """공유 레지스트리(`_origin_stage_dict`)에 무엇이 들어 있는지 출력한다.

    원천 `BeatReq`는 등록되어 있고, 요청형 `WatchReq`는 등록되어 있지 않다.
    `_define_inst_stage()`가 이 레지스트리를 아예 건드리지 않기 때문이다.
    """

    beat_stage = domain.get_origin_stage(BeatReq().get_tr_content_id())
    print(f"\n----- 원천 `BeatReq` 스테이지: 공유됨, 상위 심볼={beat_stage.output.symbols} -----")
    try:
        domain.get_origin_stage(req.get_tr_content_id())
    except KeyError:
        print("----- 요청형 `WatchReq` 스테이지: 공유 레지스트리에 없음 -----\n")


async def consume(name: str, domain: Domain, req: WatchReq, probe: bool) -> None:
    """`req`를 `{"BTC"}`로 구독해 `TAKE`건을 받고 끝낸다.

    `probe`가 참인 소비자만 첫 데이터를 받은 뒤 레지스트리를 한 번 들여다본다.
    """

    received = 0
    async with domain.request(req, {"BTC"}) as gen:
        async for data in gen:
            d = cast_model(data, WatchData)
            print(f"  [수신 {name}] ctx#{d.ctx_no} seen={d.seen} {d.symbol}={d.price:,.1f}")
            received += 1
            if probe and received == 1:
                report_registry(domain, req)
            if received == TAKE:
                break


async def run_ex(domain: Domain) -> None:
    """내용이 같은 요청 두 개를 같은 심볼로 동시에 구독한다."""

    print("===== runing ex08 =====")
    req_a = WatchReq(quote="USD")
    req_b = WatchReq(quote="USD")
    print(f"[ex08] content_id가 같은가: {req_a.get_tr_content_id() == req_b.get_tr_content_id()}")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(consume("A", domain, req_a, probe=True))
        tg.create_task(consume("B", domain, req_b, probe=False))
    print("===== finished ex08 =====")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex08을 실행한다."""

    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
