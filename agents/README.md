# Agent 개발·연결 준비

사용자 합의에 따라 김형주의 작업 범위는 구매·사고 조사 Agent입니다.
제안서의 개인별 역할표와 다르며 Harness/Oracle·MCP 서버·제품 프론트의 소유권은 변경하지 않습니다.

## 구현 상태

PR #5의 MCP 명세 v0.2와 contracts·development-baseline을 따릅니다.
`회의 확정 필요` 항목은 추천안에 맞춘 연동 초안이며 팀 확정 계약으로 간주하지 않습니다.

- 구매: 9개 필드 요청, 조회, 승인 중단·재개, 거절, 제한된 재시도, 구조화된 결과.
- 조사: 실패 검사·trace·업무 상태·지침을 읽고, 실제 조회한 근거·출처만 포함한 보고서 생성.
- 기본 도구/보고서 모델: mock/fixture. 실제 LLM을 호출하거나 추론 품질을 평가하지 않습니다.
- MCP 모드: Streamable HTTP/Bearer adapter 준비. 실제 서버·토큰으로 통합 시험은 별도입니다.
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
현재 실행 가능한 postgres/agents/frontend만 시작하며 전체 make up은 MCP·Harness 구현 후 사용합니다.
컨테이너 포트는 루트 .env의 AGENTS_PORT·FRONTEND_PORT·POSTGRES_PORT로 조정합니다.

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
- 도구 10초, 최대 12회 호출(재시도·Resource 포함), 8노드 실행, 능동 120초, 전체 600초입니다.
- 읽기 일시 오류/모호한 쓰기는 각각 최대 1회 재시도합니다. 쓰기 payload와 request_id는 그대로 유지합니다.
- 승인 대기는 능동 시간에서 제외합니다. 300초 만료는 ERROR/APPROVAL_WAIT_EXPIRED이며 거절로 바꾸지 않습니다.
- 재시작 후 승인 대기는 원래 만료시각으로 복원합니다. 진행 중이던 실행은 PROCESS_INTERRUPTED로 끝내고 자동 재실행하지 않습니다. 생성 중이었다면 결과 UNKNOWN입니다.
- MCP 모드는 시작·재개 요청에 agent_token을 받습니다. 토큰은 메모리에만 보관하고 각 실행 구간 종료 시 제거합니다. 재개 때 다시 제공해야 합니다.
- 토큰·키는 진행 기록·checkpoint·오류 응답에 남기지 않습니다. SQLite는 외부 업무 DB와 독립된 개발 저장소입니다.
- 이벤트는 Agent가 본 호출·응답·상태만 기록합니다. 실제 BUSINESS_COMMITTED/FAULT_INJECTED/VERDICT_CREATED를 만들지 않습니다.
- sequence_scope=AGENT_LOCAL은 Agent 로컬 순번입니다. 추후 Harness가 부여할 전역 sequence와 같지 않습니다.

MCP 실제 저장·승인 권한·중복 방지, Harness·제품 화면 연동, 실제 LLM 호출과 품질 검증은 후속 통합 시험입니다.
