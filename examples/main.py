"""예제 실행 진입점.

`examples/` 아래에서 `run_ex.py`를 가진 디렉터리를 예제로 자동 인식한다. 새 예제
디렉터리(`ex06/run_ex.py` 등)를 추가하면 이 파일을 고치지 않아도 바로 실행된다.

    uv run examples/main.py ex01      # 단일 예제 실행
    uv run examples/main.py serial    # 모든 예제를 순차 실행
    uv run examples/main.py parallel  # 모든 예제를 동시 실행

세 방식 모두 하나의 `Domain`을 공유한다. `parallel`은 옛 `main.py`의 동작과 같고,
`serial`은 예제끼리 스테이지가 겹치지 않은 상태를 각각 관찰할 때 쓴다.
"""

import sys
from argparse import ArgumentParser
from asyncio import TaskGroup, run
from collections.abc import Callable, Coroutine
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from trading_core import Domain

EXAMPLES_DIR = Path(__file__).resolve().parent
RUN_MODULE = "run_ex"
RUN_ATTR = "run_ex"
SERIAL = "serial"
PARALLEL = "parallel"

type RunEx = Callable[[Domain], Coroutine[Any, Any, None]]


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


async def run_examples(runners: list[RunEx], parallel: bool) -> None:
    """공유 `Domain`을 시작하고 예제 실행 함수를 순차 또는 동시에 돌린다."""

    domain = Domain()
    await domain.start()
    try:
        if parallel:
            async with TaskGroup() as tg:
                for runner in runners:
                    tg.create_task(runner(domain))
        else:
            for runner in runners:
                await runner(domain)
    finally:
        await domain.stop()


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
    runners = [load_run_ex(name) for name in selected]
    run(run_examples(runners, target == PARALLEL))


if __name__ == "__main__":
    main()
