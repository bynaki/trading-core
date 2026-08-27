# trading-core

코인·주식 실시간 스트림을 위한 **타입 안전 비동기 스트리밍 오케스트레이션 코어**입니다.

`trading-core`는 거래소나 증권사에 종속된 WebSocket 클라이언트가 **아닙니다.** 실시간
시세·체결·호가 스트림을 다룰 때 반복해서 필요한 요청 모델링, 구독 공유, 심볼별 라우팅,
의존 스트림 연결, 비동기 태스크와 자원 수명 주기를 작은 범용 런타임으로 제공합니다.
거래소별 인증·구독 메시지·응답 파싱만 어댑터로 구현하면 나머지 흐름은 같은 구조로
운용할 수 있습니다.

## 무엇을 해결하나

실시간 마켓 데이터 시스템에서는 여러 전략과 지표가 같은 종목을 동시에 구독합니다.
소비자마다 연결을 새로 만들면 연결 수와 트래픽이 불필요하게 늘어나고, 구독 추가·해제와
연결 종료도 각자 처리해야 합니다.

```text
소비자 A (BTC, ETH) ─┐
                     ├─→ 공유 원천 (BTC, ETH, XRP) ─→ 심볼 기준 fan-out ─→ 각 소비자
소비자 B (ETH, XRP) ─┘
```

- **동일 요청 공유** — 내용이 같은 요청은 하나의 원천과 컨텍스트를 공유합니다.
- **구독 합집합** — 여러 소비자가 요구한 심볼의 합집합만 어댑터에 전달합니다.
- **심볼별 fan-out** — 원천 데이터는 그 심볼을 구독한 소비자에게만 갑니다.
- **명시적 수명 주기** — 구독 구성이 달라질 때와 마지막 소비자가 떠날 때를 구분해
  정리 지점을 줍니다.
- **스트림 의존성** — 한 스트림의 출력을 다른 스트림의 입력으로 연결할 수 있습니다.
- **타입이 있는 경계** — 요청과 데이터를 Pydantic 모델로 정의하고 검증·직렬화를
  그대로 씁니다.

## 요구 사항과 설치

- Python 3.14 이상
- 런타임 의존성: [Pydantic 2](https://docs.pydantic.dev/) 하나뿐
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/bynaki/trading-core.git
cd trading-core
uv sync
```

다른 uv 프로젝트에서 직접 의존하려면 로컬 경로나 Git 저장소를 쓸 수 있습니다.

```bash
uv add /path/to/trading-core
uv add "https://github.com/bynaki/trading-core.git"
```

## 사용법을 보려면

**API는 아직 자리를 잡는 중이라 이 문서에 코드 예제를 두지 않습니다.** 대신
`examples/`에 **실행되는** 시나리오가 있습니다. 문서와 달리 예제는 낡으면 바로
깨지므로 항상 현재 API를 보여 줍니다.

```bash
uv run examples/main.py ex01      # 예제 하나
uv run examples/main.py serial    # 전체를 공유 Domain에서 순차 실행
uv run examples/main.py parallel  # 전체를 공유 Domain에서 동시 실행
uv run examples/main.py --help    # 예제 목록
```

각 예제 디렉터리에는 무엇을 왜 보여 주는지 설명한 README가 있습니다. 처음이라면
`examples/ex01`부터 보세요. 예제는 단순 API 데모가 아니라 공유·라우팅·정리 동작을
관찰하도록 짜인 시나리오입니다.

구조와 설계 원칙은 [CLAUDE.md](CLAUDE.md)에 정리되어 있습니다.

## 현재 상태

버전 `0.1.0`. **API가 바뀝니다.** 프로덕션에 쓰기 전에 아래를 확인하세요.

담당하는 것:

- 요청·데이터 모델과 내용 기반 식별자
- 어댑터 등록과 타입 기반 조회
- 내용이 같은 요청의 in-memory 원천 공유
- 소비자별 심볼 라우팅과 구독 합집합 관리
- 의존 스트림 연결
- 비동기 태스크 취소와 어댑터·컨텍스트 정리 지점

아직 담당하지 않는 것 — 어댑터에서 직접 다뤄야 합니다:

- 특정 거래소·증권사의 WebSocket/REST 클라이언트
- 인증, heartbeat, 자동 재연결, 재구독, rate limit 정책
- 거래소 심볼과 내부 표준 심볼의 변환 규칙
- sequence 누락, snapshot/delta 정합성, 중복·순서 뒤바뀜 처리
- 주문 실행, 포트폴리오, 리스크, 저장소, 전략·지표 구현
- 프로세스·서버 간 원천 공유
- bounded queue와 backpressure 정책
- 어댑터 예외를 소비자 스트림으로 전달하는 완결된 오류 채널

## 개발

코드를 고친 뒤 아래 네 검사를 모두 통과해야 합니다.

```bash
uv run ruff check .
uv run ruff format --check .   # 적용은 uv run ruff format .
uv run pyright
uv run pytest
```

`src/`를 고쳤으면 `uv run examples/main.py serial`도 한 번 돌려 보세요. 테스트가
프레임워크 불변식을 덮지만 예제까지 함께 돌지는 않습니다.

## 라이선스

[MIT License](LICENSE)
