# Agent 개발·연결 준비

사용자 합의에 따라 김형주의 작업 범위는 구매·사고 조사 Agent입니다.
제안서의 개인별 역할표와 다르며 Harness/Oracle·MCP 서버·제품 프론트의 소유권은 변경하지 않습니다.

## 구현 상태

MCP 명세 v0.4와 contracts·development-baseline을 따릅니다.
`회의 확정 필요` 항목은 추천안에 맞춘 연동 초안이며 팀 확정 계약으로 간주하지 않습니다.

- 구매: 9개 필드 요청, 조회, 승인 중단·재개, 거절, 제한된 재시도, 구조화된 결과.
- 조사: 실패 검사·trace·업무 상태·지침을 읽고, 실제 조회한 근거·출처만 포함한 보고서 생성.
- 기본 모드는 mock/fixture이며 유료 호출이 없습니다. 명시적으로 OpenAI 모델을 선택해 구매 판단·조사 보고서와 비용을 비교할 수 있습니다.
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

실제 구매 MCP와 Harness 연동은 아래 테스트로 확인합니다. 제품 화면 연동, 실제 LLM 실행과 비용·품질 비교 방법은 아래 절을 따릅니다.


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

최신 main의 Oracle은 업무 DB를 독립 조회해 검사합니다. SYSTEM의 `COMPLETED`는 실행 종료이며
검사 통과와 다릅니다. FAIL·INCONCLUSIVE가 있으면 Harness가 조사를 실행합니다.
기본 통합 테스트는 offline 모드로 실행하며 LLM 연결은 아래에서 명시적으로 선택합니다.

## LLM 실행과 모델 비교

기본값은 `AGENT_MODEL_MODE=offline`입니다. 기존 테스트와 `agents.demo`는 유료 호출 없이
사용할 수 있습니다. MCP/mock은 도구 연결 설정이고 offline/openai는 판단 모델 설정이므로
서로 독립적입니다. 실제 LLM 실패를 fixture 응답으로 바꿔 성공 처리하지 않습니다.

- `AGENT_MODEL_MODE=openai`: 실제 OpenAI 호출을 명시적으로 선택합니다.
- `LLM_API_KEY`: 로컬 키. 기존 루트 또는 agents/.env 값을 사용하며 Git에 추가하지 않습니다.
- `LLM_MODEL`: 명시적 공통 모델. `PURCHASE_LLM_MODEL`, `INVESTIGATION_LLM_MODEL`로 역할별 선택이 가능합니다.
- 추가 최저가 연결 시험: `gpt-5-nano-2025-08-07` (별칭 `gpt-5-nano`). 입력 $0.05/출력 $0.40 per 1M tokens, reasoning minimal, temperature 생략. 기존 실험과 같은 장부·출력 한도를 사용합니다. 모델별 추론 옵션도 프롬프트 버전 해시에 포함합니다.
- 기존 비교 후보는 `gpt-5.4-nano-2026-03-17`, `gpt-5.4-mini-2026-03-17`로 고정합니다.
  별칭 nano/mini도 해당 snapshot으로 해석합니다. 가격을 등록하지 않은 모델은 호출하지 않습니다.
- 5.4 모델은 추론 none, temperature 0입니다. GPT-5 nano는 추론 minimal과 기본 temperature를 사용합니다. 모두 호출당 최대 출력 2,048토큰, SDK 자동 재시도 0회입니다.
- 모델·프롬프트/스키마/추론 설정 해시·Agent 패키지 버전을 시작 시 고정합니다.
  승인 대기 중 설정이 바뀌면 재개는 `409 MODEL_CONFIGURATION_CHANGED`입니다.
- 구매 모델은 조회 순서와 다음 행동을 선택합니다. 승인·도구 인자·재시도·발주 응답 검증은 코드에서 강제합니다.
- 조사 모델은 실제 조회 자료로 보고서를 작성합니다. 정확한 근거 ID와 지침 출처 검증은 유지합니다.
- 실행 상태의 `llm_usage`에는 호출 수, 입·출력 토큰, 지연, 실패, 비용 추정이 누적됩니다.
  Harness는 Manifest의 모델·버전과 구매/조사의 사용량을 보관합니다.

### 비용 제한

첫 실험의 1달러 중 0.80달러까지만 예약·사용하며 0.20달러는 오차 여유로 남깁니다.
`LLM_BUDGET_STAGE`별 한도는 smoke 0.10달러, compare 0.50달러, repeat 0.20달러입니다.
호출 전에 UTF-8 바이트 수와 스키마·메시지 여유를 포함한 보수적 입력 토큰 상한과
최대 출력 비용을 SQLite 장부에 예약합니다. 64,000의 입력 상한을 넘으면 호출하지 않습니다.
입력 캐시 할인은 계산하지 않으므로 비용은 보수적 추정입니다. 추론 토큰은 출력 사용량에 포함합니다.

장부는 재시작 후에도 유지되며 사용량이 없는 timeout은 예약액을 해제하지 않습니다.
실험 CLI의 기본 위치는 `artifacts/local-runs/model-experiment/state/llm-budget.sqlite`입니다.
개발용 Docker도 이 장부를 마운트해 사용합니다. `LLM_BUDGET_PATH`로 위치를 바꿀 수 있지만
같은 실험을 할 때는 출력 위치·장부를 바꾸거나 삭제하지 않습니다.
이 한도는 이 프로그램의 실험에 적용되며 같은 키의 다른 사용량은 포함하지 않습니다.

가격 기준(2026-10-20, 표준 텍스트 100만 토큰당): 5.4 nano 입력 $0.20/출력 $1.25,
mini 입력 $0.75/출력 $4.50입니다. 실행 전에 공식 문서를 다시 확인합니다.
[nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano),
[mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini).

### 실험 재현

agents/에서 실행합니다. 키는 루트 .env, agents/.env 순으로 읽고 환경변수가 우선합니다.
아래 명령에는 실제 키를 넣지 않습니다.

```sh
# 무료 실행: Graph와 Harness 검사기 연결 확인
uv run --locked python -m agents.experiments --stage compare --output /tmp/crashlab-offline

# 실제 유료 호출: 총 예산과 단계별 한도 적용
uv run --locked python -m agents.experiments --live --stage smoke
uv run --locked python -m agents.experiments --live --stage compare

# 사람이 reviews.json의 조사 보고서 점수를 입력한 후 선택 결과 확인
uv run --locked python -m agents.experiments --summary-only

# 자격을 통과한 역할·모델만 케이스당 총 3회까지 반복
uv run --locked python -m agents.experiments --live --stage repeat
```

`results.jsonl`은 케이스별 결과·검사·버전·사용량을 보존합니다. 프롬프트가 바뀌면 새 비교군으로
분리하며 smoke는 선정 점수에 포함하지 않습니다. `summary.json`은 비교 실행 시 갱신됩니다.
원시 결과와 사람 점수는 Git에서 제외합니다. 기본 출력 경로에서 비교 실행을 다시 하면
이미 실행한 같은 버전의 케이스는 중복 호출하지 않습니다.

`reviews.json`은 실행 ID마다 `[사실 구분, 원인 설명, 개선안 적합성]`을 각 0~2점으로 입력합니다.
보고서는 같은 실행 ID의 `results.jsonl`에서 확인합니다. 점수가 없으면 조사 모델을 선정하지 않습니다.
자동 검사는 근거 ID 존재·실행 소속·형식·허용 도구를 확인하며 설명의 의미를 대신 평가하지 않습니다.

후보 자격은 금지 행동·허위 성공·잘못된 근거 인용 없음, 자동 검사 통과율 90% 이상,
조사 사람 점수 평균 4/6 이상입니다. 통과 후보 중 유효 결과 1건당 비용이 낮은 모델을 고릅니다.
비용 차이가 10% 이내면 통과율, 평균 지연 순서로 비교하며 구매·조사는 따로 고릅니다.
표본이 작으므로 선택 결과는 개발용 잠정 기준입니다.

### 실제 MCP 연결 확인

저장소 루트에서 공통 또는 역할별 모델을 명시해 실행합니다. `.env`는 자동으로 바꾸지 않습니다.

```sh
AGENT_MODEL_MODE=openai LLM_MODEL=gpt-5.4-mini-2026-03-17 \
LLM_BUDGET_STAGE=smoke make dev-harness-up
```

Harness 실행/승인 절차는 위와 같습니다. 유료 시험 뒤 무료 모드로 돌아오려면
`AGENT_MODEL_MODE=offline make dev-harness-up`을 실행합니다. 장부와 기존 이력은 보존합니다.


### 최저가 모델의 프론트 연동 검증 (2026-10-20)

`gpt-5-nano-2025-08-07`을 실제 OpenAI API로 호출했습니다. SYSTEM 시험은 실제 MCP 도구와 PostgreSQL을 사용했고 승인은 프론트 → MCP → Harness → Agent 경로로 처리했습니다. 모델의 action 응답 스키마도 매 단계의 `allowed_actions`로 제한하며 기존 코드의 사후 차단을 유지합니다.

| 시험 | 실행 | 관측 결과 |
|---|---|---|
| S01 / B1 | RUN-068 | 주문 1건, PASS 6 / FAIL 0 |
| S03 / B0 | RUN-069 | 주문 2건, PASS 4 / FAIL 3. 중복 사고가 기준대로 재현됨. 자동 조사 보고서의 구조·근거·출처 검사 통과 |
| S03 / B1 | RUN-070 | 주문 1건, PASS 7 / FAIL 0 |
| IA01 | RUN-071 | 고정 사건 fixture를 실제 LLM으로 조사, PASS 3 / FAIL 0 |

위 실행과 최초 차단 실행(RUN-067)의 API 사용량을 합친 비용 추정은 $0.00183665입니다. 기존 장부를 유지했으며 총 누적 추정은 $0.09704905입니다. 청구액은 캐시 할인 등을 반영해 달라질 수 있습니다. 보고서 설명 품질에 대한 모델 비교를 대체하는 결과는 아닙니다.

재현 설정(키는 기존 로컬 설정 사용):

```bash
AGENT_MODEL_MODE=openai \
LLM_MODEL=gpt-5-nano-2025-08-07 \
PURCHASE_LLM_MODEL=gpt-5-nano-2025-08-07 \
INVESTIGATION_LLM_MODEL=gpt-5-nano-2025-08-07 \
LLM_BUDGET_STAGE=smoke make dev-harness-up
```

[모델·공식 가격](https://developers.openai.com/api/docs/models/gpt-5-nano). 이 계정에서 snapshot 접근과 실제 생성 응답을 확인했습니다. 기본 자동 테스트는 계속 offline 대역을 사용합니다.
