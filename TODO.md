# TODO

- 데코레이터 콜백에서는 set(symbols) 해서 전달
- TaskManager: task에서 예외가 발생했을때 TaskManager 단에서 처리 방법
- [해결] 같은 파생 요청을 서로 다른 심볼 집합으로 동시에 구독하면 먼저 구독한 쪽이 데이터를 전혀 받지 못하던 문제.
  파생 스테이지 자신의 심볼은 SharedSender가 합집합으로 관리하는데, 상위 원천에 등록하는 심볼은 그 시점 update의 req_symbols뿐이라 같은 transq의 이전 등록을 덮어쓰고 있었다. require 변환을 set_sender() 뒤로 옮겨 합집합(current_symbols)을 입력으로 쓰도록 고쳤다.
  재현·검증: examples/ex05 (README에 내력), tests/test_ex05.py.

  남은 제약: require 콜백이 심볼에 따라 다른 상위 요청을 반환하는 것은 여전히 불가능하다. 파생 스테이지가 transq 하나로 상위 하나만 바라보기 때문이며, 필요해지면 상위 스테이지를 여러 개 드는 구조가 따로 있어야 한다.