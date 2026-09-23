"""ex09를 실제 `Domain`에서 실행하는 모듈.

이 예제 전용 `setting.toml`로 로그 모듈을 구성하고, 피드를 구독한 뒤 예제 공용 설정으로 다시
구성해 되돌린다. 재구성하면 이전 리스너가 큐를 비우고 파일 싱크를 닫는다. 마지막에 JSON 로그
파일을 **이번 실행의 발신처(instance_id)로 걸러** 읽어 보인다. 여러 서버의 로그가 모인
로그서버에서 한 프로세스의 로그만 골라 보는 것과 같은 방식이다.
"""

import asyncio
import json
import os
import socket
from collections import Counter
from pathlib import Path
from typing import Any

from trading_core import Domain, cast_model
from trading_core.logger import configure, get_logger, load_settings

if __package__:
    from .ex09 import PriceData, PriceFeedReq
else:
    from ex09 import PriceData, PriceFeedReq

SETTINGS = Path(__file__).resolve().parent / "setting.toml"
"""이 예제 전용 로그 설정."""
EXAMPLES_SETTINGS = Path(__file__).resolve().parents[1] / "setting.toml"
"""예제 공용 로그 설정. 끝날 때 이 설정으로 되돌린다."""
TAKE = 6
"""받고 끝낼 데이터 수."""

log = get_logger(__name__)


def read_own_records(path: Path, instance_id: str) -> list[dict[str, Any]]:
    """로그 파일에서 이번 실행이 남긴 레코드만 고른다. 파일은 실행마다 이어 쓰기 때문이다."""

    records = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return [r for r in records if r["instance_id"] == instance_id]


def report(path: Path, instance_id: str) -> None:
    """파일 싱크에 무엇이 남았는지 요약한다."""

    records = read_own_records(path, instance_id)

    def count_by(key: str) -> dict[str, Any]:
        """레코드를 `key` 값별로 센다. 그대로 로그의 fields로 펼친다."""

        return dict(Counter(r[key] for r in records))

    log.info(f"----- {path} 에서 instance_id={instance_id} 인 레코드 {len(records)}건 -----")
    log.info("레벨별", **count_by("level"))
    log.info("로거별", **count_by("logger"))
    log.info("태스크별", **count_by("task"))

    failed = next(r for r in records if r["exc"] is not None)
    failed["exc"]["traceback"] = failed["exc"]["traceback"].splitlines()[-1]  # 보기 좋게 줄인다
    pretty = json.dumps(failed, ensure_ascii=False, indent=2)
    log.info(f"예외를 담은 레코드 하나 (traceback은 마지막 줄만):\n{pretty}")


async def run_ex(domain: Domain) -> None:
    """로그를 구성하고 피드를 구독한 뒤, 파일 싱크에 남은 레코드를 요약한다."""

    configure(SETTINGS)  # 명시적으로 구성한다. 부르지 않으면 첫 로그 때 CWD의 setting.toml을 찾는다
    log.info("━━━━━━━━━━ 시작: 로그 모듈 쓰기 ━━━━━━━━━━", take=TAKE)

    received = 0
    async with domain.request(PriceFeedReq(base=100.0), {"BTC", "ETH"}) as gen:
        async for data in gen:
            d = cast_model(data, PriceData)
            log.info("수신", symbol=d.symbol, price=d.price)
            received += 1
            if received == TAKE:
                break
    await asyncio.sleep(0.1)  # detach 콜백이 남기는 "피드 종료" 로그를 기다린다
    log.info("구독 끝", received=received)

    # 예제 공용 설정으로 되돌린다. 이전 리스너가 큐에 남은 레코드를 모두 내보내고 파일 싱크를
    # 닫으므로 곧바로 파일을 읽을 수 있다. `shutdown()`도 큐를 비우지만, 그 뒤의 로그는 어디로도
    # 나가지 않아 이어서 도는 다른 예제의 로그까지 사라진다.
    configure(EXAMPLES_SETTINGS)

    settings = load_settings(SETTINGS)
    host = socket.gethostname()
    instance_id = f"{settings.service_name or host}@{host}:{os.getpid()}"
    report(settings.file.path, instance_id)
    # 끝의 "\n"이 다음 예제와의 사이에 빈 줄을 남긴다.
    log.info("━━━━━━━━━━ 끝 ━━━━━━━━━━\n")


async def main() -> None:
    """독립 실행용 `Domain`을 시작하고 ex09를 실행한다."""

    configure(EXAMPLES_SETTINGS)
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
