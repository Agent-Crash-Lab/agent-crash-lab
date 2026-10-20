# Harness

시험 실행·기록·판정 조립을 맡는 서비스입니다. API와 실행 규칙은 [HARNESS_SPEC.md](HARNESS_SPEC.md)를 따릅니다.

## 구현 상태

- 공개 API(`/api/**`): 시나리오 조회, 실행 생성·목록·상세, 이벤트(SSE·JSON), B0/B1 비교
- MCP용 내부 API(`/internal/runs/**`): 재개, 이벤트 제출, 조사용 검사·이벤트 조회
- Runner: S01~S03(MCP + Agent `mcp` 모드), PA01~03·IA01~03(Agent `mock` 모드)
- PA/IA 개별 시험 검사, 조사 보고서 자동 검사, Agent 이벤트 수집
- 이벤트 순번: MCP·Agent·Harness 이벤트를 1초 모았다가 실제 발생 시각(`occurred_at`) 순으로 번호를 붙임. SSE는 발생 후 약 1초 뒤에 나옴
- Oracle(`src/harness/oracle`): 함수 경계만 있음. 문관영 구현 전까지 SYSTEM 시험 검사는 비어 있음

## 로컬 설치·검증

`harness/`에서:

```sh
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

테스트는 가짜 MCP·Agent와 SQLite를 사용하며 Docker가 필요 없습니다.

## 로컬 실행

```sh
INTERNAL_API_TOKEN=dev-token HARNESS_DEV_AUTH=true \
  uv run --locked uvicorn harness.api:app --host 127.0.0.1 --port 8000
```

- `DATABASE_URL`이 없으면 `.harness-state/harness.sqlite`를 씁니다. Compose에서는 PostgreSQL `harness` schema(`harness_app`)를 씁니다.
- `HARNESS_DEV_AUTH=true`면 게이트웨이 헤더 없이 `requester-01`로 처리합니다. 배포 환경에서는 끕니다.
- 공유 자료(config·contracts·scenarios·fixtures)는 저장소에서 찾습니다. `HARNESS_PROJECT_ROOT`로 위치를 바꿀 수 있습니다.

## 수동 검증 (전체 스택)

저장소 루트에서 실행합니다. Docker와 `jq`가 필요합니다.

Spring 게이트웨이(MCP_SPEC 5.2)가 아직 없어서 실행 생성·조회는 Harness(8000)를 직접 호출합니다. 이때 Spring이 붙일 헤더 3개를 직접 붙입니다. 승인은 실제 Spring(8081) API로 합니다.

### 1. 준비와 기동

```sh
cp .env.example .env        # 처음 한 번. INTERNAL_API_TOKEN에 아무 값이나 입력
make up
make ps                     # mcp-server·agents·harness가 healthy
```

`INTERNAL_API_TOKEN`이 비어 있으면 서비스끼리 거절합니다 (503 `INTERNAL_API_TOKEN_NOT_CONFIGURED`).

### 2. 터미널 도구

새 터미널 창마다 다시 입력합니다.

```sh
TOKEN=$(grep '^INTERNAL_API_TOKEN=' .env | cut -d= -f2-)
h() { curl -s -H "X-Internal-Token: $TOKEN" -H "X-User-Id: requester-01" -H "X-User-Roles: REQUESTER" -H "Content-Type: application/json" "$@"; }
show() { h localhost:8000/api/runs/$1 | jq '{status, status_reason, outcome: .agent.result.outcome, fault: .fault.status, checks: [.checks[] | "\(.rule_id) \(.verdict) \(.reason)"]}'; }
ATOKEN=$(curl -s -X POST localhost:8081/api/auth/login -H "Content-Type: application/json" \
  -d '{"user_id":"approver-01","password":"crashlab"}' | jq -r .access_token)
```

결과가 이상하면 `jq` 없이 응답을 보면 `{"error":{"code":...}}`에 원인이 있습니다.

### 3. 개별 시험 (승인 없이 바로 끝남)

```sh
RID=$(h -X POST localhost:8000/api/runs -d '{"test_id":"PA03"}' | jq -r .run_id); echo $RID
sleep 2; show $RID
```

기대 결과: `COMPLETED`, `PA03-R1`~`R3` 모두 PASS. `PA01`, `PA02`, `IA01`~`IA03`도 같은 방식입니다. 시험은 한 번에 하나만 돌므로 앞 시험이 끝난 뒤 시작합니다 (아니면 409 `RUN_IN_PROGRESS`).

### 4. 통합 시험 S03 (사람 승인)

```sh
RID=$(h -X POST localhost:8000/api/runs -d '{"test_id":"S03","system_id":"B0"}' | jq -r .run_id); echo $RID
sleep 2; show $RID          # WAITING_APPROVAL 확인. 아직 RUNNING이면 잠시 뒤 다시

APR=$(h localhost:8000/api/runs/$RID | jq -r .approval_request.approval_request_id)
HASH=$(h localhost:8000/api/runs/$RID | jq -r .approval_request.payload_hash)
curl -s -X POST localhost:8081/api/runs/$RID/approval -H "Authorization: Bearer $ATOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"approval_request_id\":\"$APR\",\"decision\":\"APPROVED\",\"payload_hash\":\"$HASH\"}" | jq -c

sleep 5; show $RID
h localhost:8000/api/runs/$RID/events | jq -r '.events[] | "\(.sequence)\t\(.producer)\t\(.event_type)"'
```

- 승인은 300초 안에 합니다. 늦으면 `ERROR`(`APPROVAL_WAIT_EXPIRED`).
- 기대 결과 (S03-B0): `COMPLETED`, `outcome: SUCCEEDED`, `fault: APPLIED`, 이벤트에 `BUSINESS_COMMITTED` 2번(중복 발주).
- 이벤트는 발생 순서대로 번호가 붙습니다: `AGENT_APPROVAL_RECEIVED` → `AGENT_TOOL_CALLED` → `TOOL_CALLED` → `BUSINESS_COMMITTED` → `FAULT_INJECTED` → … → 재시도 → `BUSINESS_COMMITTED`.
- `S01`은 정상 발주(저장 1번), `S02`는 `"decision":"REJECTED"`로 거절(저장 0번)입니다.
- 지금은 Oracle이 없어 `checks`가 비어 있습니다.

### 5. B0/B1 비교

4단계를 `"system_id":"B1"`로 한 번 더 한 뒤, B0 실행 번호를 넣습니다.

```sh
h "localhost:8000/api/comparisons?left=RUN-00X&right=$RID" | jq '{changed, actual}'
```

기대 결과: `changed`는 `system_id`, `server_policy_version` 두 가지, `actual`의 주문 수는 B0 2건·B1 1건.

### 6. 종료된 시험에 늦은 승인

```sh
curl -s -X POST localhost:8081/api/runs/$RID/approval -H "Authorization: Bearer $ATOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"approval_request_id\":\"$APR\",\"decision\":\"APPROVED\",\"payload_hash\":\"$HASH\"}" | jq -c .error.code
```

기대 결과: `"RUN_FINALIZED"`. 끝내려면 `make down` (`make clean`은 DB까지 지움).

## 환경변수

| 변수 | 용도 |
|---|---|
| `DATABASE_URL` | 실행·이벤트 기록 (harness_app) |
| `ORACLE_DATABASE_URL` | Oracle 업무 DB 조회 (oracle_ro) |
| `MCP_URL` | mcp-server 주소 (`http://mcp-server:8081`) |
| `AGENT_URL` | Agent 주소 (`http://agents:8090`) |
| `INTERNAL_API_TOKEN` | 내부 API 공유 토큰. 비어 있으면 Harness API는 503 |
| `HARNESS_DEV_AUTH` | 개발용 인증 우회 (기본 `false`). `.env`에서 `true`로 바꾸면 Compose에서도 헤더 없이 호출 가능 |
| `HARNESS_PROJECT_ROOT` | 공유 자료 위치 |

## Agent 모델 기록

Agent의 비동기 API 형식은 유지합니다. 시작 응답의 `model_kind`, `model`, `agent_version`,
`prompt_version`을 구매 Manifest에 저장하며 조사 모델 정보는 `investigation.model_metadata`에
보관합니다. 완료 시 `agent.usage.llm`, `investigation.llm_usage`로 모델 사용량을 전달합니다.
모델 키는 Harness가 받거나 저장하지 않습니다. 모델 선택·예산과 실험 방법은
[Agent LLM 문서](../agents/README.md#llm-실행과-모델-비교)를 따릅니다.
