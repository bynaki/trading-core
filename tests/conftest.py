"""테스트 공통 픽스처."""

from collections.abc import AsyncIterator

import pytest

from trading_core import Domain

SMALL_SENDER_BUFFER = 5
"""`small_buffer_domain`이 소비자마다 쌓아 두는 데이터 상한. 발행 간격 0.01초면 금세 찬다."""


@pytest.fixture
async def domain() -> AsyncIterator[Domain]:
    """테스트마다 새 `Domain`을 시작하고, 끝나면 남은 태스크까지 정리한다."""

    d = Domain()
    await d.start()
    try:
        yield d
    finally:
        await d.stop()


@pytest.fixture
async def small_buffer_domain() -> AsyncIterator[Domain]:
    """느린 소비자가 금세 밀려 떨어지도록 `sender_buffer`를 작게 둔 `Domain`."""

    d = Domain(sender_buffer=SMALL_SENDER_BUFFER)
    await d.start()
    try:
        yield d
    finally:
        await d.stop()
