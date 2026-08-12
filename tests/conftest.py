"""테스트 공통 픽스처."""

from collections.abc import AsyncIterator

import pytest

from trading_core import Domain


@pytest.fixture
async def domain() -> AsyncIterator[Domain]:
    """테스트마다 새 `Domain`을 시작하고, 끝나면 남은 태스크까지 정리한다."""

    d = Domain()
    await d.start()
    try:
        yield d
    finally:
        await d.stop()
