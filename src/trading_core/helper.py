import inspect
import os
import hashlib


def verify_module(obj: object, _filename: str | None = None):
    module = inspect.getmodule(obj, _filename)
    if module is None:
        raise ValueError(f"'{obj}'은 모듈에 속해있어야 한다.")
    return module


def generate_id(length: int = 16) -> str:
    # os.urandom()으로 안전한 난수 생성
    random_bytes = os.urandom(32)
    # sha256 해시 적용
    sha256_hash = hashlib.sha256(random_bytes).hexdigest()
    # 원하는 길이만큼 잘라서 반환
    return sha256_hash[:length]


def generate_digest(content: str, length: int = 16):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:length]