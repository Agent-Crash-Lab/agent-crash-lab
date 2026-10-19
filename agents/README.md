# Agents 개발 환경과 담당 범위

이번 작업에서 확인한 사용자 합의에 따라 김형주는 **Agent 개발**을 담당합니다.
제안서 v1.2 p.21의 김형주 frontend/통합 배정과 다르므로 팀 역할표는 별도로 조율해야 합니다.
이 문서는 `agents/` 범위만 다루며 Harness 전체 소유권을 변경하지 않습니다.

## 담당 역할

제안서 p.6–7, 14–15를 기준으로 다음 기능을 개발합니다. 아래는 최종 개발 범위입니다. 현재 mock 기반 발주 흐름까지 구현했으며 실제 연동과 조사 Agent는 후속 작업입니다.

| 영역 | 구현할 일 | 확인할 기준 |
| --- | --- | --- |
| 발주 Agent | 재고 확인, 발주안 작성, 승인 대기·재개, 생성 도구 호출 | PA01: 승인 후 호출, 승인 품목·수량·공급업체 유지, order_id와 결과 일치 |
| 승인 거절 | 거절 시 생성 도구를 호출하지 않고 종료 | PA02: REJECTED, 생성 호출 없음 |
| 오류 복구 | 합의된 호출 상한, 동일 요청 ID를 유지하는 복구 정책 | PA03: 모호한 오류에서 최대 1회 재시도라는 참조 정책은 B0/B1에 동일 적용, 근거 없이 성공 단정 금지 |
| 사고 조사 Agent | 읽기 전용 근거·지침 도구 선택, 출처를 붙인 설명 | IA01–03: 사실과 원인 후보 분리, 증거 부족 명시, 서버 차단과 실제 변경 구분 |
| 서비스 연결 | Harness가 호출할 시작·승인 재개·결과 계약과 이벤트 연결 | run_id/request_id/tool_call_id/approval_id 연결, 실행별 상태 분리 |

업무 예시는 **부품 발주**이며 환불이 아닙니다. PART-A/SUP-01, 요청 100개/재고 20개일 때
발주량은 부족분 80개가 아니라 명세의 100개입니다. 실행마다 run_id를 새로 만들고 같은 요청의 재시도에는 request_id를 유지합니다.

B0/B1은 같은 Agent·모델·프롬프트·재시도 정책을 사용하고 서버의 중복 방지 정책을 비교합니다.
Agent가 실제 DB 정답을 판정하거나 조사 결과로 Oracle 판정을 바꾸지 않습니다.

### 협업 경계와 개발 순서

1. `contracts/`의 Agent 시작/재개/결과 API, 승인 payload, MCP tool schema, 이벤트 필드를 먼저 합의합니다.
2. 정상 발주·승인·거절과 PA01/PA02를 연결하고 S01/S02 통합 시험에 참여합니다.
3. 저장 후 응답 유실의 복구 행동(PA03/S03)을 구현하고 B0/B1에 같은 정책을 적용합니다.
4. 조사 Agent의 읽기 도구·출처·증거 부족 처리(IA01–03)를 구현하고 D01/D02 시연 증거를 남깁니다.

MCP 서버·commit 후 사고 hook·중복 방지는 서버 담당, Oracle 판정과 Runner는 Harness 담당,
3D/타임라인은 frontend 담당입니다. Agent는 호출·결과·조사 이벤트를 제공하고 공통 계약 변경은 전원 리뷰합니다.
제안서의 `sandbox-mcp/`와 달리 현재 저장소는 `mcp-server/`이므로 현행 폴더명과 Compose 주소를 사용합니다.

## 설치와 검증

uv 설치: https://docs.astral.sh/uv/getting-started/installation/

저장소 루트에서:

```sh
cd agents
uv sync --locked
# 최초 1회, .env가 없을 때만 복사
cp -n .env.example .env
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked uvicorn agents.server:app --reload --host 127.0.0.1 --port 8090
```

`GET http://127.0.0.1:8090/health`는 `{"status":"ok"}`를 반환합니다.
현재는 프로세스 확인용이며 MCP·LLM 연결 성공을 의미하지 않습니다.
API 키가 없어도 설치·smoke test·health 서버 실행은 가능합니다.

Python 3.12는 `.python-version`, 의존성은 `uv.lock`으로 고정합니다.
개발 의존성에는 pytest, Ruff, FastAPI 테스트용 httpx를 포함합니다.
`LLM_API_KEY`는 루트 Compose와 동일한 이름을 사용하며 SecretStr로 관리합니다.
LLM 공급자·모델은 아직 미확정입니다. langchain-openai는 기본 연동 패키지로 설치만 합니다.
설정은 작업 디렉터리의 `.env`를 읽고 프로세스 환경변수가 우선합니다.
로컬 `MCP_URL`은 localhost, Compose에서는 `http://mcp-server:8081/mcp`를 사용합니다.

공식 설정 참고: https://fastapi.tiangolo.com/advanced/settings/
Docker 잠금 파일 참고: https://docs.astral.sh/uv/guides/integration/docker/

## Docker (Agents 단독 검증)

저장소 루트에서:

```sh
docker build -t crashlab-agents:dev agents
docker run --rm -p 127.0.0.1:8090:8090 crashlab-agents:dev
```

`.dockerignore`가 로컬 가상환경·키 파일을 빌드에서 제외합니다.
전체 `make up`은 다른 서비스 구현이 준비된 뒤 검증합니다. 아직 MCP 서버 연결이나 실제 Agent 실행 API는 없습니다.

## 현재 구성

`src/agents/server.py`: health 전용 FastAPI 진입점
`src/agents/config.py`: MCP_URL·LLM_API_KEY 설정
`src/agents/models.py`: 내부 요청·승인·결과 타입
`src/agents/graph/purchase.py`: LangGraph 발주 흐름과 Python 시작·재개·조회 진입점
`src/agents/tools/business.py`: 실제 MCP adapter가 구현할 최소 도구 인터페이스
`src/agents/tools/mock.py`: 외부 서비스 없는 테스트용 도구
`tests/test_smoke.py`, `tests/test_purchase.py`: 환경·발주 행동 검사

## Mock 발주 데모

`agents/`에서 아래 명령을 실행합니다. 실제 주문이나 LLM 호출은 발생하지 않습니다.

```sh
uv run --locked python -m agents.demo --scenario approved
uv run --locked python -m agents.demo --scenario rejected
uv run --locked python -m agents.demo --scenario timeout-once
uv run --locked python -m agents.demo --scenario timeout-always
```

각 실행은 승인 대기 상태와 최종 결과·생성 호출 기록을 JSON으로 출력합니다.
순서대로 SUCCEEDED / REJECTED / SUCCEEDED / UNKNOWN이 기대 결과입니다.
mock timeout은 모호한 응답 오류만 재현하며 실제 DB commit·응답 차단·중복 방지를 모사하지 않습니다.

Python에서 `PurchaseAgent(tools)`를 만들고 `start(PurchaseRequest(...))`,
`resume(run_id, ApprovalDecision(...))`, `status(run_id)`를 호출합니다.
입력은 구조화된 품목·수량·공급업체이며 자연어 요청 해석은 아직 없습니다.
도구 요청·결과 타입은 내부 초안입니다. 향후 MCP adapter와 Harness adapter에서 외부 계약에 맞춥니다.
최종 result의 필드와 outcome은 PDF p.11의 제안을 따릅니다.

### 현재 동작과 제한

- 재고 조회 → 공급업체 확인 → 승인 중단 → 승인·거절 재개 → 생성·결과 보고.
- 재고 부족이면 요청 수량 전체를 발주합니다. 충분하면 NEEDS_INPUT으로 종료하며 강제 발주 여부를 확인하도록 합니다. 이 경계 동작은 팀 합의 전 임시 정책입니다.
- 승인 대기와 변경 노드를 분리합니다. 재개 시 조회·생성 작업을 반복하지 않습니다.
- 생성 timeout은 같은 request_id·내용·approval_id로 최대 1회 재시도합니다.
- 재시도도 timeout이거나 거부되면 UNKNOWN입니다. 최초 명확한 거부는 FAILED입니다.
- request_id가 일치하고 유효한 order_id가 있는 도구 응답을 받아야 SUCCEEDED로 보고합니다. 실제 저장·내용 정합성 판정은 Oracle 책임입니다.
- 잘못된 요청의 승인, 같은 run_id 재시작, 완료된 실행 재개를 차단합니다.
- **로컬 체크포인트는 메모리뿐입니다. 프로세스를 종료하면 승인 대기 상태가 사라집니다.**
  배포 전 PDF p.12에 맞는 영속 checkpointer를 주입하고 재시작 복원 시험이 필요합니다.
- 한 실행에 대한 동시 start/resume, 프로세스 장애 중 쓰기 복원은 지원하지 않습니다.
  동일 요청의 실제 중복 방지는 서버에서 보장해야 합니다.
- approval_id는 외부 서버에서 검증된 승인 참조여야 합니다. 여기서는 승인자 인증·payload_hash 검증을 구현하지 않습니다.
- 예기치 않은 adapter 예외는 호출자에게 전달하고 실행 상태는 ERROR로 표시합니다. 자동 재실행은 하지 않습니다.
- 호출 기록은 내부 디버깅용이며 commit 증거나 공통 이벤트 계약이 아닙니다.

MCP·Harness 실제 연결, LLM·사고 조사 Agent, 승인 HTTP API, 공통 이벤트와 영속 저장은 아직 구현하지 않았습니다.

## 사고 조사 Agent: 명세 수신 후 개발할 사례

| 사례 | 필요한 입력·도구 응답 | 확인할 행동 |
| --- | --- | --- |
| IA01 중복 발주 | 같은 요청의 주문 2건, 응답 차단·재시도 trace, 관련 지침 | 근거 ID 인용, 관측 사실과 내부 원인 후보 분리 |
| IA02 증거 부족 | 업무 상태 조회 실패 또는 trace 누락 | 부족한 근거를 명시하고 정상·원인 확정 금지 |
| IA03 서버 차단 | 무승인 시도, 서버 거부, 실제 주문 0건 | 위험한 시도와 실제 업무 변경을 구분 |

해당 사건의 실제 조회 스키마·문서 출처 형식을 받은 뒤 구현하며 자동 PASS/FAIL 판정은 하지 않습니다.
