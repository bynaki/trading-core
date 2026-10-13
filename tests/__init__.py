"""`trading-core` 테스트 패키지.

패키지로 두는 이유는 두 가지다. 테스트 모듈이 `tests.test_*`라는 하나의 이름으로만
import되어 모델 `model_id`(클래스명@모듈명 기반)가 흔들리지 않고, `tests.support`를
어느 테스트에서든 같은 경로로 가져올 수 있다.
"""
