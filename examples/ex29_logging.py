"""ex29: 로그 모듈 — `trading_core.logger`

지금까지 모든 예제는 `print` 대신 `trading_core.logger`로 출력했다. 이 예제는 그 로그 모듈 자체를
본다. 같은 로그 호출이 설정에 따라 콘솔(사람이 읽는 text)과 파일(JSON)로 **다르게 걸러져** 나가고,
라이브러리 내부 로그(`trading_core.*`)와 바깥 앱의 로그가 같은 곳으로 모인다.

    log = get_logger(__name__)                     # 모듈 맨 위. 이것만으로는 설정을 읽지 않는다
    log.info("수신", symbol="BTC", price=101.0)    # 키워드 인자는 레코드의 fields가 된다
    log.exception("파싱 실패", raw=raw)            # except 안에서. 트레이스백은 exc 필드로 간다

설정은 `setting.toml`의 `[log]`에 둔다. 이 예제는 자기 설정(`ex29_logging.toml`)을 쓴다.

- 루트 레벨은 DEBUG, 콘솔은 INFO 이상을 text로, 파일(`logs/ex29.jsonl`)은 DEBUG까지 JSON으로.
- `[log.levels]`로 시끄러운 로거 `ex29.wire`를 INFO에 묶는다. 파일이 DEBUG여도 그 DEBUG는 안 나간다.

`configure(path)`는 선택이다. 부르지 않으면 **첫 로그 때** 환경변수 `TRADING_CORE_SETTINGS`, 그다음
현재 디렉터리의 `setting.toml`을 찾고, 없으면 기본값(콘솔 text만)으로 동작한다. 로그 호출은 큐에
넣고 곧바로 돌아오고, 실제 출력은 전용 스레드가 한다. 이벤트 루프를 막지 않는다.

배우는 것
- 레코드는 루트 레벨과 싱크 레벨을 **둘 다** 넘어야 그 싱크로 나간다. 그래서 콘솔에 없는 DEBUG가
  파일에는 있다.
- 레코드마다 발신처(`service`·`host`·`pid`·`instance_id`)와 태스크 이름(`task`)이 실린다. 여러
  서버의 로그가 한곳에 모여도 `instance_id`로 한 프로세스의 것만 고를 수 있다.
- 트레이스백은 메시지가 아니라 레코드의 `exc` 필드(`type`·`message`·`traceback`)로 따로 간다.

실행
    uv run examples/ex29_logging.py

기대 출력 (`<host>`·`<pid>`는 실행 환경마다 다르다)
    …Z INFO  [ex29-local@<host>:<pid>] __main__: ━━━━━━━━━━ 시작: 로그 모듈 ━━━━━━━━━━ {take=6}
    …Z INFO  [ex29-local@<host>:<pid>] __main__: 피드 연결 {base=100.0}
    …Z INFO  [ex29-local@<host>:<pid>] __main__: 구독 시작 {symbols=['BTC', 'ETH']}
    …Z INFO  [ex29-local@<host>:<pid>] __main__: 수신 {symbol=BTC, price=101.0}
    …Z INFO  [ex29-local@<host>:<pid>] __main__: 수신 {symbol=ETH, price=103.0}
    …Z INFO  [ex29-local@<host>:<pid>] __main__: 수신 {symbol=BTC, price=103.0}
    …Z ERROR [ex29-local@<host>:<pid>] __main__: 페이로드 파싱 실패, 이 틱은 건너뛴다 {...}
    Traceback (most recent call last):
      ...
    ValueError: could not convert string to float: '??'
    …Z WARNING [ex29-local@<host>:<pid>] __main__: 가격 급변 감지 {symbol=BTC, price=105.0}
    …  (수신 세 줄)
    …Z INFO  [ex29-local@<host>:<pid>] __main__: 구독 정리 {ticks=7}
    …Z INFO  [ex29-local@<host>:<pid>] __main__: 피드 종료 {ticks=7}
    INFO  __main__: ----- logs/ex29.jsonl에서 이번 실행의 레코드 21건 -----
    INFO  __main__: 레벨별 {INFO=11, DEBUG=8, ERROR=1, WARNING=1}
    INFO  __main__: 로거별 {__main__=19, trading_core.tasks=2}
    INFO  __main__: 태스크별
      {"Task-1": 9, "PriceFeedReq@__main__:...:2": 11, "Task-9": 1}
    INFO  __main__: 예외를 담은 레코드 {msg=페이로드 파싱 실패, ..., exc_type=ValueError}

앞쪽 줄은 이 예제의 설정(`format = "text"`)이라 시각과 발신처가 붙고, 뒤쪽 짧은 줄은 공용 설정
(`"text.simple"`)으로 되돌린 뒤의 것이다. 형식이 바뀌는 곳이 곧 설정이 바뀐 곳이다.

- 콘솔에 없던 DEBUG 8건이 파일에는 있다. `틱 발행` 6건과 `trading_core.tasks`(태스크 제출·취소)
  2건이다. 라이브러리 내부 로그도 같은 설정을 따른다.
- `ex29.wire`는 로거별 집계에 없다. `[log.levels]`로 눌렀기 때문이다.
- `task`는 레코드가 어느 태스크에서 나왔는지 알려 준다. generator 본문과 `finally`는 코어가 스테이지
  이름을 붙인 태스크에서, init과 소비자의 `수신`은 구독을 연 쪽(`Task-1`)에서 돈다. 같은 binder
  코드라도 어느 지점이 어느 태스크에서 도는지가 이 필드로 드러난다(태스크 이름의 번호는 실행
  방식에 따라 다르다).

알아둘 점
- 로그 모듈은 프로세스 전역인 루트 로거에 붙는다. 이 예제가 구성을 바꾸는 동안에는 함께 도는
  다른 예제의 줄도 이 설정을 따른다(`parallel`로 돌리면 보인다).
- 끝날 때 `shutdown()`이 아니라 공용 설정으로 **다시 `configure()`**한다. 재구성해도 이전 리스너가
  큐를 비우고 파일을 닫으므로 곧바로 파일을 읽을 수 있다. `shutdown()` 뒤의 로그는 어디로도 나가지
  않아, 뒤따르는 예제의 로그까지 사라진다.
- 다른 예제는 로거 이름을 `"ex05.tick"`처럼 직접 준다. 직접 실행하면 `__name__`이 `__main__`이
  되어 어느 예제의 줄인지 안 보이기 때문이다. 이 예제만 `get_logger(__name__)` 관용구를 보인다.

설계는 `docs/log.spec.md`, 모든 설정 키의 설명은 저장소 루트의 `setting.example.toml`에 있다.

다음: ex30_data_types.py — 요청 하나가 여러 종류의 데이터를 줄 때
"""

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

from trading_core import DataModel, Domain, SourceRequest, cast_model, initialize
from trading_core.logger import configure, get_identity, get_logger, load_settings

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
"""예제 공용 로그 설정. 끝날 때 이 설정으로 되돌린다."""
OWN_SETTINGS = Path(__file__).resolve().parent / "ex29_logging.toml"
"""이 예제 전용 로그 설정."""
TAKE = 6
"""받고 끝낼 데이터 수."""

log = get_logger(__name__)
"""이 모듈의 로거. 이름은 모듈 경로(`ex29_logging`, 직접 실행하면 `__main__`)가 된다."""
wire = get_logger("ex29.wire")
"""틱마다 원시 페이로드를 찍는 시끄러운 로거. 설정의 `[log.levels]`로 누른다."""


# ===== binder 쪽: 곳곳에서 로그를 남기는 소스 요청 =====


class PriceFeedReq(SourceRequest):
    base: float


class PriceData(DataModel):
    price: float


class FeedCtx:
    def __init__(self, req: PriceFeedReq) -> None:
        self.req = req
        self.ticks = 0
        log.info("피드 연결", base=req.base)


@initialize
def feed(req: PriceFeedReq) -> FeedCtx:
    return FeedCtx(req)


def parse(raw: str) -> float:
    """원시 페이로드를 가격으로 바꾼다. 깨진 페이로드면 `ValueError`다."""

    return float(raw.split("=")[1])


@feed
async def _(ctx: FeedCtx, symbols: set[str]):
    log.info("구독 시작", symbols=sorted(symbols))
    try:
        while True:
            for i, symbol in enumerate(sorted(symbols)):
                ctx.ticks += 1
                price = ctx.req.base + ctx.ticks + i
                # 네 번째 틱은 깨진 페이로드를 흉내 낸다.
                raw = f"{symbol}=??" if ctx.ticks == 4 else f"{symbol}={price}"
                wire.debug("원시 페이로드", raw=raw)  # [log.levels]로 눌려 어디에도 안 나간다

                try:
                    price = parse(raw)
                except ValueError:
                    log.exception("페이로드 파싱 실패, 이 틱은 건너뛴다", symbol=symbol, raw=raw)
                    continue

                log.debug("틱 발행", symbol=symbol, price=price, tick=ctx.ticks)  # 파일에만 간다
                if ctx.ticks % 5 == 0:
                    log.warning("가격 급변 감지", symbol=symbol, price=price)
                yield PriceData(symbol=symbol, price=price)
            await asyncio.sleep(0.2)
    finally:
        log.info("구독 정리", ticks=ctx.ticks)


@feed.detached
async def _(ctx: FeedCtx):
    log.info("피드 종료", ticks=ctx.ticks)


# ===== 소비자 쪽 =====


def read_own_records(path: Path, instance_id: str) -> list[dict[str, Any]]:
    """로그 파일에서 이번 실행이 남긴 레코드만 고른다. 파일은 실행마다 이어 쓰기 때문이다."""

    records = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return [r for r in records if r["instance_id"] == instance_id]


async def run_ex(domain: Domain) -> None:
    configure(OWN_SETTINGS)  # 여기부터 이 예제의 설정을 따른다
    instance_id = get_identity().instance_id
    log.info("━━━━━━━━━━ 시작: 로그 모듈 ━━━━━━━━━━", take=TAKE)

    received = 0
    async with domain.stream(PriceFeedReq(base=100.0), {"BTC", "ETH"}) as stream:
        async for data in stream:
            item = cast_model(data, PriceData)
            log.info("수신", symbol=item.symbol, price=item.price)
            received += 1
            if received == TAKE:
                break
    await asyncio.sleep(0.1)  # detached가 남기는 "피드 종료"를 기다린다

    # 공용 설정으로 되돌린다. 이전 리스너가 큐를 비우고 파일을 닫으므로 곧바로 읽을 수 있다.
    configure(SETTINGS)

    path = load_settings(OWN_SETTINGS).file.path
    records = read_own_records(path, instance_id)

    def count_by(key: str) -> dict[str, Any]:
        """레코드를 `key` 값별로 센다. 그대로 로그의 fields로 펼친다."""

        return dict(Counter(r[key] for r in records))

    levels, loggers = count_by("level"), count_by("logger")
    log.info(f"----- {path}에서 이번 실행의 레코드 {len(records)}건 -----")
    log.info("레벨별", **levels)
    log.info("로거별", **loggers)
    log.info("태스크별", **count_by("task"))

    # `parallel`로 돌면 다른 예제의 레코드도 섞이므로 이 모듈의 로거로 고른다.
    failed = next(r for r in records if r["exc"] is not None and r["logger"] == __name__)
    log.info("예외를 담은 레코드", msg=failed["msg"], exc_type=failed["exc"]["type"])

    assert received == TAKE
    assert levels.get("DEBUG", 0) > 0  # 콘솔(INFO)에는 없던 DEBUG가 파일에는 있다
    assert "ex29.wire" not in loggers  # [log.levels]로 눌렀다
    assert failed["exc"]["type"] == "ValueError"
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    configure(SETTINGS)
    domain = Domain()
    await domain.start()
    try:
        await run_ex(domain)
    finally:
        await domain.stop()


if __name__ == "__main__":
    asyncio.run(main())
