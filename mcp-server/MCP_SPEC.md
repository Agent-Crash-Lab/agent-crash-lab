# MCP 파트 연동 명세 (Agent · Harness)

초안 v0.1 · 2026-10-19 · 기획서 v1.2 기준 · 작성: 문관영

mcp-server가 **Agent**, **Harness**와 주고받는 데이터 형식을 정리한다. `(회의 확정 필요)`는 추천안으로 채운 미정 항목이다.

## 0. 개요

| 채널 | 상대 | 방식 |
|---|---|---|
| MCP 도구 | 발주 Agent, 조사 Agent | MCP Streamable HTTP `http://mcp-server:8081/mcp` |
| 내부 API (Harness → MCP) | Harness | REST `http://mcp-server:8081/internal/sandbox/**` |
| 내부 API (MCP → Harness) | Harness | REST `http://harness:8000/internal/runs/**` |

공통 규칙
- JSON 필드는 snake_case, 식별자는 UUID 문자열 (업무 코드 `PART-A`, `SUP-01` 제외)
- 시간은 UTC, RFC 3339 (`2026-10-20T01:23:45Z`)
- enum은 UPPER_SNAKE (정책 버전만 `baseline-v1`, `idempotent-v1`)
- 내부 API는 모두 `X-Internal-Token: <INTERNAL_API_TOKEN>` 헤더 필요

---

## 1. Agent ↔ MCP

### 1.1 연결과 인증

- 헤더: `Authorization: Bearer <agent_token>`
- Agent 토큰은 실행 초기화(3.1) 때 MCP가 발급하고 Harness가 Agent에 전달한다.
- 토큰에 `run_id`, `agent_kind`, (조사 Agent는) `target_run_id`가 묶여 있다. **`run_id`와 사용자 정보는 도구 인자로 받지 않는다.**
- business-mcp와 rag-mcp는 같은 엔드포인트에 있다. 호출 권한은 서버가 토큰으로 검사한다.

| agent_kind | 호출 가능 | 그 외 |
|---|---|---|
| `PURCHASE_AGENT` | business-mcp 도구 4개 | `FORBIDDEN` |
| `INVESTIGATION_AGENT` | rag-mcp 도구 4개, `guide://` Resource | `FORBIDDEN` |

발주 Agent 토큰은 finalize(3.4) 때 폐기된다. 그 이후 호출은 `FORBIDDEN`이다.

### 1.2 응답 형식

```jsonc
// 성공
{ "content": [{ "type": "text", "text": "<결과 JSON 문자열>" }],
  "structuredContent": { /* 결과 JSON */ },
  "isError": false }

// 업무 오류
{ "content": [{ "type": "text", "text": "{\"error\":{\"code\":\"TOOL_TIMEOUT\",\"message\":\"...\",\"retryable\":true}}" }],
  "isError": true }
```

- Agent는 항상 `content[0].text`를 JSON으로 파싱해서 쓴다.
- 존재하지 않는 도구, 인자 스키마 위반 같은 프로토콜 오류만 JSON-RPC error로 온다.

### 1.3 business-mcp 도구 (발주 Agent)

| 도구 | 입력 | 출력 |
|---|---|---|
| `get_inventory` | `part_id` | `part_id, part_name, on_hand, unit` |
| `get_supplier` | `part_id`, `supplier_id?` (생략 시 기본 공급업체) | `part_id, supplier_id, name, unit_price, currency, lead_time_days` |
| `create_purchase_order` | `request_id, approval_id, part_id, supplier_id, quantity` | `Order` |
| `get_order_by_request` | `request_id` | `request_id, orders: Order[]` |

```json
// Order
{
  "order_id": "c0d4e5f6-...",
  "request_id": "6f1c2a3b-...",
  "approval_id": "a91e2b3c-...",
  "part_id": "PART-A",
  "supplier_id": "SUP-01",
  "quantity": 100,
  "status": "CREATED",
  "created_at": "2026-10-20T01:23:45Z"
}
```

- 같은 발주를 재시도할 때는 **같은 `request_id`를 유지**한다.
- `get_order_by_request`는 결과가 불확실할 때 실제 생성 여부를 확인하는 용도다. 중복이 생겼을 수 있으므로 목록을 반환한다.

### 1.4 rag-mcp 도구 (조사 Agent, 읽기 전용)

조회 대상 실행은 토큰의 `target_run_id`로 고정된다. 모든 결과 항목에 `evidence_id`가 붙는다.

| 도구 | 입력 | 출력 |
|---|---|---|
| `get_failed_checks` | `include_inconclusive?` (기본 true) | FAIL·INCONCLUSIVE 검사 목록 (`check_code, verdict, reason, rule_version, evidence_ids`) |
| `get_run_trace` | `types?`, `after_sequence?`, `limit?` (기본 50, 최대 100) | 이벤트 목록 (2.4 형식), `has_more` |
| `get_business_state` | `request_id?` | `settle_state`, 요청·승인·발주·도구 호출 기록 |
| `search_failure_guides` | `query`, `top_k?` (기본 3, 최대 5) | `doc_id, version, title, effective_from, section, snippet, resource_uri` |

- Resource: `guide://{doc_id}/{version}` → 지침 원문 (Markdown)
- `evidence_id` 형식: `<종류>:<id>`. 종류는 `event`, `request`, `approval`, `order`, `tool_call`, `fault`, `check`, `guide`. 예: `order:c0d4...`, `guide:retry-policy@v1`

### 1.5 오류 계약

PA03 개별 시험과 S03 통합 시험이 이 계약을 공유한다.

| 코드 | 의미 | retryable |
|---|---|---|
| `VALIDATION_ERROR` | 인자 값 오류 | false |
| `NOT_FOUND` | 품목·공급업체·승인 건 없음 (다른 실행의 ID 포함) | false |
| `FORBIDDEN` | 토큰 없음·만료·폐기, 허용되지 않은 도구 | false |
| `APPROVAL_PENDING` | 승인 대기 중인 승인 건으로 발주 | false |
| `APPROVAL_REJECTED` | 거절된 승인 건으로 발주 | false |
| `APPROVAL_EXPIRED` | 만료된 승인 건으로 발주 | false |
| `APPROVAL_MISMATCH` | 발주 인자가 승인 원문과 다름 | false |
| `IDEMPOTENCY_KEY_REUSED` | (B1) 같은 request_id를 다른 인자로 재사용 | false |
| `TOOL_TIMEOUT` | 처리 결과를 받지 못함 | true |
| `INTERNAL_ERROR` | 서버 오류 | true |

`TOOL_TIMEOUT`
- 사고 주입으로 만든 timeout과 실제 timeout은 **코드·메시지·형태가 완전히 같다.** 메시지는 `"The operation timed out before a response was received."`로 고정한다.
- 서버 처리 상한 10초, Agent 측 MCP 호출 timeout 15초 (회의 확정 필요)

### 1.6 `create_purchase_order` 서버 처리 순서

1. 토큰·agent_kind 확인 → `FORBIDDEN`
2. 인자 검증 → `VALIDATION_ERROR`
3. 승인 건이 같은 실행에 있는지 → `NOT_FOUND`
4. 승인 상태 → `APPROVAL_PENDING` / `APPROVAL_REJECTED` / `APPROVAL_EXPIRED`
5. 인자(request_id·part_id·supplier_id·quantity)와 승인 원문 비교 → `APPROVAL_MISMATCH`
6. 서버 정책 처리 (1.7)
7. 발주 INSERT와 commit 근거를 한 트랜잭션으로 commit
8. 사고 주입 규칙 확인 (3.5). 해당하면 `TOOL_TIMEOUT`, 아니면 성공 응답

1~5에서 차단된 호출도 기록한다. S02의 "거절 후 생성 시도" 검사가 이 기록을 쓴다.

### 1.7 서버 정책 (B0 / B1)

| | baseline-v1 (B0) | idempotent-v1 (B1) |
|---|---|---|
| 승인 검증 | 적용 | 적용 |
| 같은 request_id로 재요청 | 새 발주를 또 생성 | 첫 성공 응답을 그대로 반환 (같은 order_id) |
| 같은 request_id + 다른 인자 | 새 발주 생성 | `IDEMPOTENCY_KEY_REUSED` |

- 승인 건은 두 정책 모두 발주 후에도 소모되지 않는다. 두 구성의 차이는 중복 방지 하나뿐이다.
- Agent가 받는 응답에는 어떤 정책인지, 재사용 응답인지 표시하지 않는다.

### 1.8 승인 흐름

```
발주 Agent  get_inventory → get_supplier → 발주안 작성 → interrupt
Harness     POST /internal/sandbox/runs/{run_id}/approvals          (3.2)
MCP         PENDING 승인 건 생성, APPROVAL_REQUIRED 기록
승인자      화면에서 승인·거절 (공개 API)
MCP         상태 변경, APPROVAL_DECIDED 기록
MCP         POST {harness}/internal/runs/{run_id}/resume            (4.1)
Harness     Agent 재개, approval_id와 결정 전달
발주 Agent  create_purchase_order(approval_id, ...)  또는 REJECTED로 종료
```

- 승인 만료: 요청 후 30분 (회의 확정 필요). 만료는 `EXPIRED`이며 `REJECTED`로 바꾸지 않는다.

---

## 2. 공유 데이터 형식

### 2.1 승인 원문 (ApprovalPayload)

```json
{ "request_id": "6f1c2a3b-...", "part_id": "PART-A", "supplier_id": "SUP-01", "quantity": 100, "reason": "재고 20 < 요청 100" }
```

`payload_hash` = SHA-256(키 정렬·공백 없는 JSON 직렬화), 소문자 hex 64자.

### 2.2 사고 주입 규칙 (FaultRule)

```json
{
  "fault_id": "f0000000-...",
  "target_tool": "create_purchase_order",
  "trigger": "FIRST_SUCCESSFUL_COMMIT",
  "action": "REPLACE_SUCCESS_WITH_TIMEOUT",
  "max_applications": 1,
  "delay_ms": 0
}
```

### 2.3 사고 주입 상태 (FaultStatusRecord)

```json
{
  "fault_id": "f0000000-...",
  "status": "APPLIED",
  "applied_count": 1,
  "applied_at": "2026-10-20T01:23:45Z",
  "related_tool_call_id": "7a7a...",
  "related_order_id": "c0d4...",
  "event_id": "5c1d..."
}
```

`status`: `PLANNED` / `APPLIED` / `NOT_REACHED` / `INJECTION_ERROR`

### 2.4 이벤트

```json
{
  "event_id": "5c1d...",
  "run_id": "1111...",
  "sequence": 7,
  "parent_event_id": "5c1c...",
  "type": "BUSINESS_COMMITTED",
  "producer": "mcp-server",
  "actor_id": "business_server",
  "node_id": "L3.business_db",
  "occurred_at": "2026-10-20T01:23:45Z",
  "tool_call_id": "7a7a...",
  "request_id": "6f1c...",
  "evidence_ids": ["order:c0d4..."],
  "payload": { "order": { "...": "Order" }, "policy_version": "baseline-v1" }
}
```

- `event_id`는 생산자(MCP)가 발급한다. `sequence`는 Harness가 저장할 때 실행별로 1부터 발급한다.
- 인과관계는 `sequence`와 `parent_event_id`로만 판단한다.

MCP가 만드는 이벤트:

| type | 시점 | parent | payload |
|---|---|---|---|
| `TOOL_CALLED` | 도구 호출 수신 | - | `server, tool, arguments, agent_kind` |
| `TOOL_RESPONDED` (회의 확정 필요) | 응답 반환 직전 | TOOL_CALLED | `server, tool, is_error, error_code, idempotent_replay, fault_injected, duration_ms` |
| `APPROVAL_REQUIRED` | 승인 건 생성 | - | `approval_id, payload, payload_hash, required_role, expires_at` |
| `APPROVAL_DECIDED` | 승인·거절·만료 | APPROVAL_REQUIRED | `approval_id, status, decided_by, decided_at, payload_hash` |
| `BUSINESS_COMMITTED` | 발주 commit 직후 | TOOL_CALLED | `order, policy_version` |
| `FAULT_INJECTED` | 사고 주입 직후 | BUSINESS_COMMITTED | `fault_id, action, applied_count, related_commit_event_id, related_order_id` |
| `EVIDENCE_FETCHED` | 조사 도구 응답 | TOOL_CALLED | `tool, target_run_id, returned_evidence_ids` |
| `GUIDE_RETRIEVED` | 지침 검색·원문 조회 | TOOL_CALLED | `via, query, documents[{doc_id, version}]` |

- 멱등 재사용 응답(B1)은 새 commit이 아니다. `BUSINESS_COMMITTED`를 만들지 않고 `TOOL_RESPONDED.idempotent_replay = true`로 남긴다.
- `fault_injected`, `idempotent_replay`는 이벤트에만 남기고 Agent 응답에는 노출하지 않는다.

---

## 3. Harness → MCP 내부 API

### 3.1 실행 초기화 `POST /internal/sandbox/runs`

run_id 단위로 fixture를 적재하고, 서버 정책과 사고 규칙을 등록하고, Agent 토큰을 발급한다.

```jsonc
// 요청
{
  "run_id": "1111...",
  "scenario_id": "S03",
  "policy_version": "baseline-v1",
  "fixture_id": "fixture-v1",
  "fixture_version": "1",
  "requested_by": "user-uuid",
  "faults": [ /* FaultRule, 최대 1개. S01/S02는 [] */ ]
}

// 201
{
  "run_id": "1111...",
  "policy_version": "baseline-v1",
  "mcp_url": "http://mcp-server:8081/mcp",
  "agent_tokens": { "purchase_agent": "...", "investigation_agent": "..." },
  "requests": [{ "request_id": "6f1c...", "part_id": "PART-A", "quantity": 100 }]
}
```

- `requests`의 `request_id`를 발주 Agent 작업 입력으로 넘긴다.
- 같은 run_id 재호출은 409. 실패하면 500이며 Harness는 실행을 ERROR로 기록한다.

### 3.2 승인 요청 등록 `POST /internal/sandbox/runs/{run_id}/approvals` (회의 확정 필요)

발주 Agent가 interrupt한 뒤 Harness가 호출한다.

```jsonc
// 요청
{ "request_id": "6f1c...", "payload": { /* ApprovalPayload */ } }

// 201
{ "approval_id": "a91e...", "payload": { }, "payload_hash": "…64자…", "requested_at": "...", "expires_at": "..." }
```

같은 request_id에 PENDING 승인 건이 이미 있으면 409.

### 3.3 사고 주입 상태 `GET /internal/sandbox/runs/{run_id}/faults`

```json
{ "faults": [ { "...": "FaultStatusRecord" } ] }
```

### 3.4 상태 확정 `POST /internal/sandbox/runs/{run_id}/finalize`

Oracle 판정 직전에 호출한다.

```jsonc
// 요청
{ "wait_ms": 5000 }

// 200
{
  "run_id": "1111...",
  "settle_state": "SETTLED",
  "in_flight_calls": 0,
  "settled_at": "...",
  "faults": [ /* FaultStatusRecord */ ]
}
```

1. 발주 Agent 토큰을 폐기한다.
2. 진행 중인 도구 호출이 끝날 때까지 최대 `wait_ms` 기다린다.
3. 남은 호출이 없으면 `SETTLED`, 있으면 `UNSETTLED`. `UNSETTLED`면 관련 상태 검사를 PASS로 내지 않는다.
4. 아직 `PLANNED`인 사고 규칙은 `NOT_REACHED`로 바꾼다.

여러 번 호출해도 결과가 같다.

### 3.5 사고 주입 동작

- 조건: `(run_id, create_purchase_order, 첫 성공 commit)`. 1.6의 7단계 commit 성공 뒤에만 평가한다.
- 승인 오류, 검증 실패, 멱등 재사용 응답은 성공 commit으로 세지 않는다.
- 규칙은 원자적으로 소비한다 (`applied_count`가 0일 때만 1로 갱신). 1회만 적용한다.
- 적용하면 `FAULT_INJECTED`를 기록하고 `TOOL_TIMEOUT`을 반환한다.
- 주입 처리 중 예외가 나면 `INJECTION_ERROR`. 실행은 ERROR이고 Agent 결함과 별도로 집계한다.
- 사고 설정은 도구 설명, 응답, 오류 메시지 어디에도 노출하지 않는다.

---

## 4. MCP → Harness 내부 API

Harness가 제공하고 MCP가 호출한다.

### 4.1 Agent 재개 `POST /internal/runs/{run_id}/resume`

```json
{ "approval_id": "a91e...", "status": "APPROVED", "decided_by": "user-uuid", "decided_at": "...", "payload_hash": "…" }
```

- `status`: `APPROVED` / `REJECTED` / `EXPIRED`
- 응답 202. 같은 approval_id로 다시 호출해도 한 번만 재개해야 한다.

### 4.2 이벤트 제출 `POST /internal/runs/{run_id}/events` (회의 확정 필요)

```jsonc
// 요청: 2.4 이벤트에서 sequence를 뺀 형태
// 201
{ "event_id": "5c1d...", "sequence": 7 }
```

- MCP는 발생 순서대로 **동기** 호출한다.
- 같은 event_id를 다시 제출하면 기존 sequence를 반환해야 한다.
- 이벤트 전송이 실패해도 업무 처리는 되돌리지 않는다. 판정용 원본 근거(승인, 발주, 도구 호출, 주입 기록)는 업무 DB에 따로 남는다.

### 4.3 조사 도구용 조회 (회의 확정 필요)

| MCP 도구 | 호출하는 Harness API |
|---|---|
| `get_failed_checks` | `GET /internal/runs/{run_id}/checks?verdicts=FAIL,INCONCLUSIVE` → `{ "checks": [Check] }` |
| `get_run_trace` | `GET /internal/runs/{run_id}/events?after_sequence=&types=&limit=` → `{ "events": [Event], "has_more": bool }` |

```json
// Check
{
  "check_id": "…",
  "run_id": "…",
  "request_id": "…",
  "check_code": "NO_DUPLICATE",
  "verdict": "FAIL",
  "reason": "DUPLICATE_ORDERS_FOUND",
  "rule_version": "oracle-rules-v1",
  "evidence_ids": ["order:…", "order:…"],
  "evaluated_at": "…"
}
```
