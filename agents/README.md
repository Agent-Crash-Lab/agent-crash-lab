# Agent 개발·연결 준비

사용자 합의에 따라 김형주의 작업 범위는 구매·사고 조사 Agent입니다.
제안서의 개인별 역할표와 다르며 Harness/Oracle·MCP 서버·제품 프론트의 소유권은 변경하지 않습니다.

## 구현 상태

MCP 명세 v0.4와 contracts·development-baseline을 따릅니다.
`회의 확정 필요` 항목은 추천안에 맞춘 연동 초안이며 팀 확정 계약으로 간주하지 않습니다.

- 구매: 9개 필드 요청, 조회, 승인 중단·재개, 거절, 제한된 재시도, 구조화된 결과.
- 조사: 실패 검사·trace·업무 상태·지침을 읽고, 실제 조회한 근거·출처만 포함한 보고서 생성.
- 기본 도구/보고서 모델: mock/fixture. 실제 LLM을 호출하거나 추론 품질을 평가하지 않습니다.
- Harness: 실제 서비스에서 PA01~03·IA01~03과 구매 S01/S02/S03 × B0/B1을 검증합니다.
- 조사 MCP 모드의 실제 Oracle 실패 판정에 따른 자동 실행은 후속 범위입니다.
- 내부 API, SQLite checkpoint·실행 기록·진행 이벤트, 재시작 후 승인 재개.
- 기존 제품 화면은 정적 데모입니다. 화면과 Agent를 연결하지 않습니다.

## 로컬 설치·검증

저장소의 agents/에서:

```sh
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m agents.demo --scenario approved
uv run --locked python -m agents.demo --scenario rejected
uv run --locked python -m agents.demo --scenario timeout-once
uv run --locked python -m agents.demo --scenario timeout-always
uv run --locked python -m agents.demo --scenario ia01
uv run --locked python -m agents.demo --scenario ia02
uv run --locked python -m agents.demo --scenario ia03
```

CLI는 임시 SQLite를 사용하며 실제 업무 서버·모델 호출이 없습니다.
HTTP 서버는 `.env`의 INTERNAL_API_TOKEN을 설정한 뒤 실행합니다.

```sh
uv run --locked uvicorn agents.server:app --host 127.0.0.1 --port 8091
```

기본 저장 위치는 현재 디렉터리의 `.agent-state/`입니다. AGENT_STATE_DIR로 변경할 수 있습니다.
공유 자료는 저장소에서 자동 탐색하며 AGENT_PROJECT_ROOT로 위치를 지정할 수 있습니다.
API 키와 모델명은 실제 모델 연결 시 결정합니다. 지금은 LLM 키가 없어도 동작합니다.

## Docker 개발 환경

저장소 루트에서:

```sh
make dev-up
make dev-ps
make agent-demo scenario=ia01
make dev-logs s=agents
make dev-down
```

Docker Compose 2.24.4 이상이 필요합니다. 루트 .env는 .env.example을 최초 한 번 복사해 준비합니다.
`make dev-up`은 postgres/agents/frontend를 시작합니다. 실제 MCP도 필요하면 `make dev-mcp-up`을 사용합니다.
Harness까지 연결하려면 `make dev-harness-up`을 사용합니다.
컨테이너 포트는 루트 .env의 AGENTS_PORT·MCP_SERVER_PORT·FRONTEND_PORT·POSTGRES_PORT·HARNESS_PORT로 조정합니다.

- 개발 프로젝트는 agent-crash-lab-dev이며 통합 환경과 볼륨을 분리합니다.
- Agent의 `/state`를 agent_state 볼륨에 저장하므로 컨테이너 재시작·재생성 후에도 승인 대기를 복원합니다.
- config/contracts/fixtures는 읽기 전용으로 마운트합니다. Agent는 업무 DB를 직접 읽거나 쓰지 않습니다.
- dev-down은 컨테이너·네트워크만 제거합니다. DB와 Agent 상태 볼륨은 유지합니다.
- 코드 변경 시 dev-up으로 다시 빌드합니다. 자동 코드 새로고침은 없습니다.
- 단일 Uvicorn 프로세스로 실행합니다. 다중 worker/replica는 지원하지 않습니다.

## Agent 내부 API 초안

모든 업무 API에 `X-Internal-Token`이 필요합니다. 미설정이면 503, 잘못된 토큰은 401입니다.
이 토큰은 서비스 접근용이며 사용자별 실행 소유권·승인자 인증은 Spring/Harness에서 확인해야 합니다.
MCP의 `/internal/runs/...` 콜백을 이 서비스에 구현한 것이 아닙니다.

| 경로 | 의미 |
| --- | --- |
| GET /health | 프로세스 확인. MCP/LLM readiness는 아님 |
| POST /internal/agent-runs | 실행 접수, 202 |
| GET /internal/agent-runs/{run_id} | 상태·승인 payload hash·최종 결과 |
| POST /internal/agent-runs/{run_id}/resume | 승인·거절 재개, 202 |
| GET /internal/agent-runs/{run_id}/events?after_sequence=0 | 로컬 순번 기준 진행 기록, 최대 100개 |

구매 시작 예시:

```json
{
  "run_id": "RUN-001",
  "agent_kind": "PURCHASE_AGENT",
  "mode": "mock",
  "fixture_id": "purchase-normal",
  "request": {
    "request_id": "REQ-001", "request_version": 1,
    "part_id": "PART-A", "quantity": 100, "unit_price_minor": 12000,
    "currency": "KRW", "supplier_id": "SUP-01",
    "plant_id": "PLANT-A", "purchasing_org_id": "PUR-A"
  }
}
```

승인 대기 조회 응답의 payload_hash를 사용해 재개합니다. 아래 해시는 자리표시자입니다.
mock API 테스트의 승인 입력은 실제 서버 승인 증거가 아닙니다.

```json
{
  "request_id": "REQ-001", "approval_id": "AP-001", "decision": "APPROVED",
  "approver_id": "approver-01", "decided_at": "2026-10-19T08:00:00Z",
  "payload_hash": "대기 응답에서 받은 64자리 소문자 SHA-256"
}
```

조사 시작 예시:

```json
{
  "run_id": "INV-001", "agent_kind": "INVESTIGATION_AGENT", "mode": "mock",
  "target_run_id": "TARGET-001", "fixture_id": "ia01-v1"
}
```

조사 fixture는 ia01-v1(중복), ia02-v1(증거 부족), ia03-v1(서버 차단)입니다.
원본 fixture의 기대 정답·평가표는 Agent/모델 입력에서 제외합니다.
보고서의 출처 ID 검증은 의미적 주장을 자동 채점하는 것이 아닙니다. 설명 적합성은 사람 검토가 필요합니다.

## 실행·복구 규칙

- 동시에 활성 실행 1개(승인 대기 포함). 다른 실행·중복 시작은 409입니다.
- 승인 전 생성 없음, 거절 후 생성 없음. 같은 승인 재전송은 상태만 반환하고 중복 생성하지 않습니다.
- 승인 요청 ID·payload hash 불일치는 422, 다른 승인으로 중복 재개는 409, 없는 실행은 404입니다.
- 구매 payload 9개를 sort_keys=true/ensure_ascii=false/공백 없는 UTF-8 JSON으로 SHA-256 처리합니다. run_id는 해시에서 제외합니다.
- 재고 부족 시 요청 수량 전체를 발주합니다. 재고 충분 시 NEEDS_INPUT으로 종료하는 동작은 임시 정책입니다.
- MCP·mock 도구와 Resource 대기는 모두 개발 기준의 10초입니다. 최대 12회 호출(재시도·Resource 포함), 8노드 실행, 능동 120초, 전체 600초입니다.
- 읽기 일시 오류/모호한 쓰기는 각각 최대 1회 재시도합니다. 쓰기 payload와 request_id는 그대로 유지합니다.
- 승인 대기는 능동 시간에서 제외합니다. 300초 만료는 ERROR/APPROVAL_WAIT_EXPIRED이며 거절로 바꾸지 않습니다.
- 재시작 후 승인 대기는 원래 만료시각으로 복원합니다. 진행 중이던 실행은 PROCESS_INTERRUPTED로 끝내고 자동 재실행하지 않습니다. 생성 중이었다면 결과 UNKNOWN입니다.
- MCP 모드는 시작·재개 요청에 agent_token을 받습니다. 토큰은 메모리에만 보관하고 각 실행 구간 종료 시 제거합니다. 재개 때 다시 제공해야 합니다.
- 토큰·키는 진행 기록·checkpoint·오류 응답에 남기지 않습니다. SQLite는 외부 업무 DB와 독립된 개발 저장소입니다.
- 이벤트는 Agent가 본 호출·응답·상태만 기록합니다. 실제 BUSINESS_COMMITTED/FAULT_INJECTED/VERDICT_CREATED를 만들지 않습니다.
- sequence_scope=AGENT_LOCAL은 Agent 로컬 순번입니다. Harness가 부여하는 실행별 공통 sequence와 같지 않습니다.

실제 구매 MCP와 Harness 연동은 아래 테스트로 확인합니다. 제품 화면 연동, 실제 LLM 호출과 품질 검증은 후속 작업입니다.


## 실제 구매 MCP 통합 테스트

저장소 루트의 `.env`에서 비어 있지 않은 `INTERNAL_API_TOKEN`을 설정합니다.
Agent와 MCP 서버가 같은 값을 사용합니다. `DEMO_USER_PASSWORD`도 MCP 설정과 같아야 하며 기본값은 `crashlab`입니다.
기존 `.env`와 DB 볼륨을 유지하고 실행합니다.

```sh
# 저장소 루트
make dev-mcp-up
make dev-ps

# agents/에서 실행 (.env 값을 현재 터미널의 환경변수로 전달)
cd agents
set -a
. ../.env
set +a
MCP_INTEGRATION_URL="http://127.0.0.1:${MCP_SERVER_PORT:-8081}" \
AGENT_INTEGRATION_URL="http://127.0.0.1:${AGENTS_PORT:-8090}" \
uv run --locked pytest -q tests/integration/test_mcp_purchase.py
```

- 위 명령은 Docker의 Agent HTTP API → 실제 MCP → PostgreSQL을 확인합니다.
- `AGENT_INTEGRATION_URL`을 생략하면 Agent API를 테스트 프로세스 안에서 실행하고, MCP·PostgreSQL은 실제 서버를 사용합니다.
- `MCP_INTEGRATION_URL`을 설정하지 않으면 일반 `pytest`에서 이 테스트 6개를 건너뜁니다.
- 테스트마다 고유 run_id를 발급합니다. 기존 실행은 수정하지 않으며 테스트 실행 기록은 업무 DB에 남습니다.
- 실제 서버에서 받은 요청·토큰을 사용하고, 실제 공개 승인 API에서 승인·거절을 저장합니다.
- Harness가 없으므로 테스트가 승인 결과를 Agent 재개 API로 직접 전달합니다. 자동 재개·Harness 이벤트 수집을 검증한 것은 아닙니다.
- 이 테스트의 실행은 Harness에 등록하지 않습니다. 최신 MCP가 승인 저장 후 콜백 실패를
  `503 HARNESS_RESUME_FAILED`로 알리면 저장된 승인만 Agent에 직접 전달합니다.
  실제 콜백 연결 검증은 아래 Harness 통합 테스트에서 수행합니다.
- 이 테스트는 구매 흐름의 통합 확인이며 Oracle 판정이나 LLM 품질 평가가 아닙니다.

| 시나리오 | B0 발주 수 | B1 발주 수 |
| --- | --- | --- |
| S01 정상 승인 | 1 | 1 |
| S02 거절 | 0 | 0 |
| S03 저장 후 응답 유실·동일 요청 재시도 | 2 | 1 |

발주 수는 Agent의 응답이 아니라 MCP finalize API의 PostgreSQL 관측 결과로 확인합니다.
요청 payload 유지·호출 수·사고 주입 1회·동일 승인 재전송도 검사합니다.
B0의 발주 2건은 사고 재현용 서버 정책에 따른 결과이며 성공적인 중복 방지를 뜻하지 않습니다.

## 실제 Harness 통합 테스트

Harness 명세 v0.3의 기존 비동기 API를 사용합니다. Harness가 500ms마다 상태와
Agent 이벤트를 조회하고, MCP의 승인 콜백을 받아 Agent를 재개합니다.
별도의 동기 구매 API나 외부 도구 응답 fixture 입력은 제공하지 않습니다.

저장소 루트에서 실행합니다. `.env`는 기존 파일을 사용하고 덮어쓰지 않습니다.

```sh
cd "$(git rev-parse --show-toplevel)"
set -a
. ./.env
set +a
make dev-harness-up
make dev-ps
cd agents
HARNESS_INTEGRATION_URL="http://127.0.0.1:${HARNESS_PORT:-8000}" \
MCP_INTEGRATION_URL="http://127.0.0.1:${MCP_SERVER_PORT:-8081}" \
uv run --locked pytest -v tests/integration/test_harness_flow.py
```

기대 결과는 **9 passed**입니다. PA01~03·IA01~03이 각각 한 시험이며,
S01·S02·S03은 각각 B0/B1을 순서대로 실행해 비교합니다.
실행 주소를 지정하지 않으면 기본 테스트에서 이 9개 시험은 건너뜁니다.
기본 테스트는 `uv run --locked pytest`로 확인합니다.

- PA01/PA03은 승인 후 성공, PA02는 거절 후 생성 호출 없이 종료합니다.
- IA01~03은 조사 보고서와 Harness의 형식·근거·읽기 전용 도구 검사를 확인합니다.
- SYSTEM 시험은 실제 MCP 로그인·승인 API를 사용합니다. 테스트가 Agent를 직접 재개하지 않습니다.
- 동일 승인 콜백 재전송 후에도 주문 수는 S01 1/1건, S02 0/0건, S03 2/1건(B0/B1)입니다.
- 실제 PostgreSQL 관측을 반영한 비교 API, 이벤트 순번·중복·이력 조회·SSE 종료를 확인합니다.
- 모든 시험은 순차 실행합니다. MCP 단독 테스트와 동시에 실행하면 Agent의 단일 실행 제한에 걸립니다.
- 테스트는 실행 이력을 추가하며 기존 DB·checkpoint·볼륨을 지우지 않습니다.
- 실패 후 승인 대기가 남으면 상세 상태를 확인하고 기존 실행을 처리하거나 300초 만료를 기다립니다.
  기존 볼륨 삭제로 해결하지 않습니다.

Harness Swagger는 `http://127.0.0.1:<HARNESS_PORT>/docs`, Agent Swagger는
`http://127.0.0.1:<AGENTS_PORT>/docs`입니다. 둘의 기본 포트는 각각 8000, 8090이며
실제 주소는 `.env`의 포트를 사용합니다. Harness 공개 API에는 내부 토큰과
`X-User-Id: requester-01`, `X-User-Roles: REQUESTER` 헤더가 필요합니다.
사람이 시험을 실행하고 승인하는 순서는 [Harness 수동 검증](../harness/README.md#수동-검증-전체-스택)을 따릅니다.
개발 프로젝트를 유지하려면 기동·종료는 `make dev-harness-up` / `make dev-down`을 사용합니다.

현재 Oracle은 빈 검사 목록을 반환합니다. SYSTEM의 `COMPLETED`와 주문 수 확인은
업무 규칙 판정 통과를 뜻하지 않습니다. 실패 판정에 따른 자동 조사는 Oracle 구현 후
별도로 검증하며, 이번 조사 연동은 IA01~03으로 확인합니다. 실제 LLM은 호출하지 않습니다.
