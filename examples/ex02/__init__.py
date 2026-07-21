"""공통 원천 스트림을 여러 파생 요청이 공유하는 의존 요청 예제.

``origin``은 꽃·개·고양이 이름을 한 번에 담은 공통 데이터를 생성하고,
``refer``는 그 원천에 의존하여 사용자가 요청한 종류의 이름만 선별한다.
``Domain``은 같은 내용의 요청을 하나의 스테이지로 공유하고, 각 스테이지가
필요로 하는 심볼의 합집합을 계산하여 데이터를 해당 구독자에게 전달한다.

이 패키지는 요청 의존성 선언, ``Receiver``를 통한 단계 연결, 원천 데이터의
재사용, 파생 데이터 변환 및 컨텍스트 정리 과정을 함께 보여준다.
"""

from .origin import NamingAllData, NamingAllReq
from .refer import NamingData, NamingReq

__all__ = ["NamingAllData", "NamingAllReq", "NamingData", "NamingReq"]
