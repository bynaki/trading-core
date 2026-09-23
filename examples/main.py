"""예제 실행 진입점.

`examples/` 아래에서 `run_ex.py`를 가진 디렉터리를 예제로 자동 인식한다. 새 예제
디렉터리(`ex06/run_ex.py` 등)를 추가하면 이 파일을 고치지 않아도 바로 실행된다.

    uv run examples/main.py ex01      # 단일 예제 실행
    uv run examples/main.py serial    # 모든 예제를 순차 실행
    uv run examples/main.py parallel  # 모든 예제를 동시 실행

세 방식 모두 하나의 `Domain`을 공유한다. `parallel`은 옛 `main.py`의 동작과 같고,
`serial`은 예제끼리 스테이지가 겹치지 않은 상태를 각각 관찰할 때 쓴다.

출력은 모두 `trading_core.logger`로 남긴다. 시작할 때 예제 공용 설정(`examples/setting.toml`)으로
구성하며, 줄마다 붙는 로거 이름(`ex01`, `ex05.origin` 등)으로 어느 예제의 어느 부분이 남긴
줄인지 구분한다. `parallel`처럼 여러 예제의 줄이 섞여도 이 이름으로 가려 볼 수 있다.
"""

import sys
from argparse import ArgumentParser
from asyncio import TaskGroup, run
from collections.abc import Callable, Coroutine
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from trading_core import Domain
from trading_core.logger import configure, get_logger

EXAMPLES_DIR = Path(__file__).resolve().parent
SETTINGS = EXAMPLES_DIR / "setting.toml"
RUN_MODULE = "run_ex"
RUN_ATTR = "run_ex"
SERIAL = "serial"
PARALLEL = "parallel"

type RunEx = Callable[[Domain], Coroutine[Any, Any, None]]

log = get_logger("examples")


def discover_examples() -> list[str]:
    """`run_ex.py`를 가진 하위 디렉터리 이름을 정렬해 돌려준다."""

    return sorted(
        path.parent.name
        for path in EXAMPLES_DIR.glob(f"*/{RUN_MODULE}.py")
        if not path.parent.name.startswith((".", "_"))
    )


def load_run_ex(name: str) -> RunEx:
    """예제 디렉터리의 `run_ex.run_ex` 코루틴 함수를 불러온다.

    `examples/`를 import 경로에 넣어 `ex01.run_ex`처럼 패키지 형태로 로드한다.
    이 시점에 예제 모듈이 실행되면서 binder 등록도 함께 끝난다.
    """

    root = str(EXAMPLES_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)

    module = import_module(f"{name}.{RUN_MODULE}")
    runner = getattr(module, RUN_ATTR, None)
    if not callable(runner):
        raise SystemExit(f"{name}/{RUN_MODULE}.py에 호출 가능한 '{RUN_ATTR}'가 없다.")
    return cast(RunEx, runner)


async def run_examples(runners: dict[str, RunEx], parallel: bool) -> None:
    """공유 `Domain`을 시작하고 예제 실행 함수를 순차 또는 동시에 돌린다."""

    mode = PARALLEL if parallel else SERIAL
    log.info(f"예제 실행 ({mode}): {', '.join(runners)}\n")  # 끝의 "\n"은 첫 예제 앞의 빈 줄
    domain = Domain()
    await domain.start()
    try:
        if parallel:
            async with TaskGroup() as tg:
                for runner in runners.values():
                    tg.create_task(runner(domain))
        else:
            for runner in runners.values():
                await runner(domain)
    finally:
        await domain.stop()
    log.info("예제 실행 끝")


def main() -> None:
    """명령행 인자를 해석해 선택한 예제를 실행한다."""

    names = discover_examples()
    if not names:
        raise SystemExit(f"{EXAMPLES_DIR}에서 '{RUN_MODULE}.py'를 가진 예제를 찾지 못했다.")

    parser = ArgumentParser(description="trading-core 예제를 실행한다.")
    parser.add_argument(
        "target",
        metavar="TARGET",
        choices=[*names, SERIAL, PARALLEL],
        help=(
            f"실행할 예제 이름({', '.join(names)}) 또는 "
            f"'{SERIAL}'(전체 순차 실행) · '{PARALLEL}'(전체 동시 실행)"
        ),
    )
    target = cast(str, parser.parse_args().target)

    selected = names if target in (SERIAL, PARALLEL) else [target]
    runners = {name: load_run_ex(name) for name in selected}
    configure(SETTINGS)
    run(run_examples(runners, target == PARALLEL))


if __name__ == "__main__":
    main()
