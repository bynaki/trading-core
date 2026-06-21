# CLAUDE.md

trading-core 개발/실행 가이드. 모든 명령은 **uv** 환경에서 실행한다.

## 환경

- Python **3.14** (`.python-version`, uv가 자동 인식)
- 런타임 의존성: **pydantic**
- 개발 도구: ruff(린트+포맷) · mypy(타입) · pytest(테스트)


## 개발 워크플로

```bash
uv run ruff check .          # 린트
uv run ruff format .         # 포맷 적용
uv run ruff format --check . # 포맷 검사(수정 없이)
uv run mypy                  # 타입 체크 (strict)
uv run pytest                # 테스트
```

코드 변경 후에는 위 4개(ruff check / format / mypy / pytest)가 모두 통과해야 한다.

> `uv run`은 항상 프로젝트 `.venv`에서 실행하므로 별도의 `activate`가 필요 없다.


## 의존성 관리

```bash
uv add <package>            # 런타임 의존성 추가
uv add --dev <package>      # 개발 의존성 추가
```
