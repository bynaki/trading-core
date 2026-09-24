"""`ids.py` 명세 — digest/id 생성과 정의 모듈 찾기."""

from trading_core.ids import generate_digest, generate_id, verify_module


def test_generate_digest_is_deterministic():
    """같은 입력은 항상 같은 digest를, 다른 입력은 다른 digest를 낸다."""

    assert generate_digest("a") == generate_digest("a")
    assert generate_digest("a") != generate_digest("b")
    assert len(generate_digest("a")) == 16
    assert len(generate_digest("a", 8)) == 8


def test_generate_id_is_random_with_requested_length():
    """`generate_id()`는 요청한 길이의 서로 다른 값을 낸다."""

    assert len(generate_id()) == 16
    assert len(generate_id(8)) == 8
    assert generate_id() != generate_id()


def test_verify_module_returns_defining_module():
    """`verify_module()`은 객체가 정의된 모듈을 돌려준다."""

    assert verify_module(generate_id).__name__ == "trading_core.ids"
