"""binder 안에서 `trading_core.logger`로 로그를 남기는 원천 예제.

바깥 앱의 코드라고 생각하면 된다. 로거는 `get_logger(__name__)`으로 얻으므로 이름이 이 모듈
경로(`ex09.ex09` 또는 `ex09`)가 되고, `trading_core` 접두는 붙지 않는다.
"""

from asyncio import sleep

from trading_core import DataModel, SourceRequest, initialize
from trading_core.logger import get_logger

log = get_logger(__name__)
"""이 모듈의 로거. 로거를 얻는 것만으로는 설정 파일을 읽지 않는다."""

wire = get_logger("ex09.wire")
"""틱마다 원시 페이로드를 찍는 시끄러운 로거. `setting.toml`의 `[log.levels]`로 누른다."""


class PriceFeedReq(SourceRequest):
    """심볼별 가격을 흉내 내는 피드 요청."""

    base: float


class PriceData(DataModel):
    price: float


class FeedCtx:
    """스테이지 수명 동안 공유되는 컨텍스트. 실제라면 거래소 연결을 들고 있을 자리다."""

    def __init__(self, req: PriceFeedReq):
        self.req = req
        self.ticks = 0
        log.info("피드 연결", base=req.base, content_id=req.tr_content_id)


@initialize
def feed(req: PriceFeedReq) -> FeedCtx:
    return FeedCtx(req)


def parse(raw: str) -> float:
    """원시 페이로드를 가격으로 바꾼다. 깨진 페이로드면 `ValueError`다."""

    return float(raw.split("=")[1])


@feed
async def _(ctx: FeedCtx, symbols: set[str]):
    """구독 심볼을 돌며 가격을 발행한다. 레벨별 로그와 잡은 예외의 기록을 보인다."""

    log.info("구독 시작", symbols=sorted(symbols))
    try:
        while True:
            for i, symbol in enumerate(sorted(symbols)):
                ctx.ticks += 1
                # 네 번째 틱은 깨진 페이로드를 흉내 낸다.
                price = ctx.req.base + ctx.ticks + i
                raw = f"{symbol}=??" if ctx.ticks == 4 else f"{symbol}={price}"
                wire.debug("원시 페이로드", raw=raw)  # [log.levels]로 눌려 어디에도 안 나간다

                try:
                    price = parse(raw)
                except ValueError:
                    # 트레이스백은 메시지가 아니라 레코드의 `exc` 필드로 따로 간다.
                    log.exception("페이로드 파싱 실패, 이 틱은 건너뛴다", symbol=symbol, raw=raw)
                    continue

                log.debug("틱 발행", symbol=symbol, price=price, tick=ctx.ticks)  # 파일에만 간다
                if ctx.ticks % 5 == 0:
                    log.warning("가격 급변 감지", symbol=symbol, price=price)
                yield PriceData(symbol=symbol, price=price)
            await sleep(0.2)
    finally:
        # 구독 갱신 단위의 정리 지점. 여기 남긴 로그도 같은 싱크로 간다.
        log.info("구독 정리", symbols=sorted(symbols), ticks=ctx.ticks)


@feed.detached
async def _(ctx: FeedCtx):
    log.info("피드 종료", ticks=ctx.ticks)
