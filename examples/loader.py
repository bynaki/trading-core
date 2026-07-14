"""CLI 모듈 로더.

지정한 파이썬 파일을 모듈로 불러와 실행한다. 파일 안의 @task/@stage 데코레이터가
실행되면서 전역 레지스트리에 등록된다.

    uv run examples/main.py examples/ex01.py
"""

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import trading_core as tc


class Stage[Treq: tc.RequestModel]:
    def __init__(self, req: Treq):
        self._req_model = req


def load_module(path: Path) -> ModuleType:
    """path가 가리키는 .py 파일을 모듈로 로드해 실행한다."""
    if not path.is_file():
        raise FileNotFoundError(f"파일을 찾을 수 없다: {path}")

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"모듈 스펙을 만들 수 없다: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="파이썬 모듈 파일을 로드한다.")
    parser.add_argument("path", type=Path, help="로드할 .py 파일 경로")
    args = parser.parse_args()

    module = load_module(args.path)
    print(f"로드 완료: {module.__name__} ({args.path})")
    print(f"StageDefiner 갯수: {len(tc.StageDefiner._stage_dict)}")  # type: ignore


if __name__ == "__main__":
    main()
