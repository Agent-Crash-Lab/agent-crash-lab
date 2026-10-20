-- sandbox 스키마 초기 구조. MCP_SPEC v0.3 기준.
-- 이 파일은 mcp_app 계정으로 실행된다 (application.yml). init.sql의 기본 권한 규칙에 따라
-- 여기서 만든 테이블은 oracle_ro가 읽을 수 있다. 예외는 맨 아래에서 회수한다.
--
-- 규칙
-- * 실행별 데이터는 모두 run_id를 키에 포함한다. ID(PO-001 등)는 실행마다 새로 시작한다.
-- * payload는 MCP_SPEC 0.1의 9개 필드 JSON 그대로 저장한다 (drafts oracle-observation과 같은 모양).
-- * 끝난 실행의 데이터는 지우지 않는다 (B0/B1 비교, 이력 재생).

-- ---------------------------------------------------------------- 실행

CREATE TABLE run_context (
    run_id                text        PRIMARY KEY,
    scenario_id           text        NOT NULL,
    server_policy_version text        NOT NULL CHECK (server_policy_version IN ('baseline-v1', 'idempotent-v1')),
    fixture_id            text        NOT NULL,
    requested_by          text        NOT NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    -- finalize(3.4) 결과. 확정 전에는 NULL
    finalized_at          timestamptz,
    snapshot_complete     boolean,
    pending_tool_calls    integer
);

-- 실행 안에서 순번 ID(PO-001, AP-001 …)와 commit/decision 순번을 발급한다.
-- UPDATE … RETURNING으로 한 트랜잭션 안에서 원자적으로 증가시킨다.
CREATE TABLE id_counter (
    run_id     text    NOT NULL REFERENCES run_context (run_id),
    kind       text    NOT NULL,
    last_value integer NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, kind)
);

-- ---------------------------------------------------------------- 실행별 seed 복제 (purchase-seed.json)

CREATE TABLE part (
    run_id  text NOT NULL REFERENCES run_context (run_id),
    part_id text NOT NULL,
    name    text NOT NULL,
    unit    text NOT NULL,
    PRIMARY KEY (run_id, part_id)
);

CREATE TABLE inventory (
    run_id             text    NOT NULL,
    part_id            text    NOT NULL,
    plant_id           text    NOT NULL,
    available_quantity integer NOT NULL CHECK (available_quantity >= 0),
    unit               text    NOT NULL,
    inventory_version  integer NOT NULL DEFAULT 1 CHECK (inventory_version >= 1),
    PRIMARY KEY (run_id, part_id, plant_id),
    FOREIGN KEY (run_id, part_id) REFERENCES part (run_id, part_id)
);

CREATE TABLE supplier (
    run_id           text    NOT NULL REFERENCES run_context (run_id),
    supplier_id      text    NOT NULL,
    status           text    NOT NULL,
    unit_price_minor integer NOT NULL CHECK (unit_price_minor >= 0),
    currency         text    NOT NULL,
    supplier_version integer NOT NULL DEFAULT 1 CHECK (supplier_version >= 1),
    PRIMARY KEY (run_id, supplier_id)
);

-- 품목·공급업체·공장·구매조직별 공급 자격 (R06, 확장 범위. seed에 있으므로 함께 복제)
CREATE TABLE approved_supply_source (
    run_id            text    NOT NULL,
    part_id           text    NOT NULL,
    supplier_id       text    NOT NULL,
    plant_id          text    NOT NULL,
    purchasing_org_id text    NOT NULL,
    allowed           boolean NOT NULL,
    policy_version    integer NOT NULL,
    PRIMARY KEY (run_id, part_id, supplier_id, plant_id, purchasing_org_id),
    FOREIGN KEY (run_id, part_id) REFERENCES part (run_id, part_id),
    FOREIGN KEY (run_id, supplier_id) REFERENCES supplier (run_id, supplier_id)
);

-- 서버에 등록된 구매 요청. 같은 request_id의 가장 큰 request_version이 최신이다.
CREATE TABLE purchase_request (
    run_id          text        NOT NULL REFERENCES run_context (run_id),
    request_id      text        NOT NULL,
    request_version integer     NOT NULL CHECK (request_version >= 1),
    payload         jsonb       NOT NULL,
    payload_hash    char(64)    NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, request_id, request_version)
);

-- ---------------------------------------------------------------- 승인 (MCP_SPEC 1.8, 3.2, 5.3)

-- 승인자에게 보여줄 payload를 서버에 고정해 둔 대기 건
CREATE TABLE approval_request (
    run_id              text        NOT NULL,
    approval_request_id text        NOT NULL,
    request_id          text        NOT NULL,
    request_version     integer     NOT NULL,
    payload             jsonb       NOT NULL,
    payload_hash        char(64)    NOT NULL,
    status              text        NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DECIDED', 'EXPIRED')),
    requested_at        timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    -- APPROVAL_REQUIRED 이벤트 ID. APPROVAL_DECIDED의 parent로 쓴다
    required_event_id   text,
    PRIMARY KEY (run_id, approval_request_id),
    FOREIGN KEY (run_id, request_id, request_version)
        REFERENCES purchase_request (run_id, request_id, request_version)
);

-- 같은 요청에 대기 중인 승인 요청은 하나뿐
CREATE UNIQUE INDEX approval_request_one_pending
    ON approval_request (run_id, request_id) WHERE status = 'PENDING';

-- 결정된 승인. 컬럼은 drafts oracle-observation의 approval row와 같다.
CREATE TABLE approval (
    run_id              text        NOT NULL,
    approval_id         text        NOT NULL,
    approval_request_id text        NOT NULL,
    request_id          text        NOT NULL,
    request_version     integer     NOT NULL,
    approver_id         text        NOT NULL,
    decision            text        NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    payload             jsonb       NOT NULL,
    payload_hash        char(64)    NOT NULL,
    revoked             boolean     NOT NULL DEFAULT false,
    decision_sequence   integer     NOT NULL,
    authority_valid     boolean     NOT NULL,
    decided_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, approval_id),
    UNIQUE (run_id, approval_request_id),
    UNIQUE (run_id, decision_sequence),
    FOREIGN KEY (run_id, approval_request_id) REFERENCES approval_request (run_id, approval_request_id)
);

-- ---------------------------------------------------------------- 발주 (MCP_SPEC 1.6, 1.7)

-- B0에서 중복이 실제로 생겨야 하므로 (run_id, request_id)에 UNIQUE를 두지 않는다.
CREATE TABLE purchase_order (
    run_id             text        NOT NULL,
    order_id           text        NOT NULL,
    request_id         text        NOT NULL,
    request_version    integer     NOT NULL,
    approval_id        text        NOT NULL,
    payload            jsonb       NOT NULL,
    payload_hash       char(64)    NOT NULL,
    status             text        NOT NULL DEFAULT 'CREATED' CHECK (status = 'CREATED'),
    commit_sequence    integer     NOT NULL,
    committed_at       timestamptz NOT NULL DEFAULT now(),
    tool_call_id       text        NOT NULL,
    commit_evidence_id text        NOT NULL,
    PRIMARY KEY (run_id, order_id),
    UNIQUE (run_id, commit_sequence),
    FOREIGN KEY (run_id, approval_id) REFERENCES approval (run_id, approval_id)
);

CREATE INDEX purchase_order_by_request ON purchase_order (run_id, request_id);

-- idempotent-v1(B1) 전용. 발주 INSERT와 같은 트랜잭션에서 기록한다.
CREATE TABLE idempotency_record (
    run_id       text        NOT NULL,
    request_id   text        NOT NULL,
    payload_hash char(64)    NOT NULL,
    order_id     text        NOT NULL,
    response     jsonb       NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, request_id),
    FOREIGN KEY (run_id, order_id) REFERENCES purchase_order (run_id, order_id)
);

-- ---------------------------------------------------------------- 증거 (MCP_SPEC 0.2, 1.6, 3.3, 3.5)

-- 서버에서 차단된 호출도 기록한다 (R05). finalize는 IN_FLIGHT 수로 snapshot_complete를 정한다.
CREATE TABLE tool_call (
    run_id            text        NOT NULL REFERENCES run_context (run_id),
    tool_call_id      text        NOT NULL,
    agent_kind        text        NOT NULL CHECK (agent_kind IN ('PURCHASE_AGENT', 'INVESTIGATION_AGENT')),
    server            text        NOT NULL CHECK (server IN ('business-mcp', 'rag-mcp')),
    tool              text        NOT NULL,
    arguments         jsonb       NOT NULL,
    status            text        NOT NULL DEFAULT 'IN_FLIGHT' CHECK (status IN ('IN_FLIGHT', 'COMPLETED')),
    is_error          boolean,
    error_code        text,
    fault_injected    boolean     NOT NULL DEFAULT false,
    idempotent_replay boolean     NOT NULL DEFAULT false,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    PRIMARY KEY (run_id, tool_call_id)
);

CREATE INDEX tool_call_in_flight ON tool_call (run_id) WHERE status = 'IN_FLIGHT';

CREATE TABLE fault_rule (
    run_id               text        NOT NULL REFERENCES run_context (run_id),
    fault_id             text        NOT NULL,
    tool_name            text        NOT NULL,
    trigger              text        NOT NULL,
    target_error_code    text        NOT NULL,
    max_applied_count    integer     NOT NULL CHECK (max_applied_count >= 1),
    applied_count        integer     NOT NULL DEFAULT 0,
    status               text        NOT NULL DEFAULT 'PLANNED'
                                     CHECK (status IN ('PLANNED', 'APPLIED', 'NOT_REACHED', 'INJECTION_ERROR')),
    applied_at           timestamptz,
    related_tool_call_id text,
    related_order_id     text,
    evidence_id          text,
    error_message        text,
    PRIMARY KEY (run_id, fault_id),
    CHECK (applied_count BETWEEN 0 AND max_applied_count)
);

-- 근거 목록. refs에는 관련 ID를 담는다 (예: {"order_id": "PO-001"})
CREATE TABLE evidence (
    run_id      text        NOT NULL REFERENCES run_context (run_id),
    evidence_id text        NOT NULL,
    kind        text        NOT NULL CHECK (kind IN ('BUSINESS_COMMITTED', 'FAULT_INJECTED', 'BUSINESS_SNAPSHOT')),
    refs        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, evidence_id)
);

-- ---------------------------------------------------------------- 인증 (MCP_SPEC 1.1, 5.3)

-- Agent 토큰은 원문을 저장하지 않고 SHA-256 해시만 저장한다.
CREATE TABLE agent_token (
    token_hash char(64)    PRIMARY KEY,
    run_id     text        NOT NULL REFERENCES run_context (run_id),
    agent_kind text        NOT NULL CHECK (agent_kind IN ('PURCHASE_AGENT', 'INVESTIGATION_AGENT')),
    issued_at  timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);

-- ---------------------------------------------------------------- 공용 (실행과 무관)

-- 로그인 계정 = seed 사용자. 서버 시작 시 적재한다.
CREATE TABLE app_user (
    user_id           text   PRIMARY KEY,
    password_hash     text   NOT NULL,
    roles             text[] NOT NULL,
    purchasing_org_id text
);

-- 로그인 토큰. Agent 토큰과 같이 원문 대신 SHA-256 해시만 저장한다.
CREATE TABLE user_session (
    token_hash char(64)    PRIMARY KEY,
    user_id    text        NOT NULL REFERENCES app_user (user_id),
    issued_at  timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

-- rag-mcp 지침 문서 (guides/index.json). 서버 시작 시 적재한다.
CREATE TABLE guide_document (
    document_id text        NOT NULL,
    version     text        NOT NULL,
    title       text        NOT NULL,
    body        text        NOT NULL,
    loaded_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, version)
);

-- ---------------------------------------------------------------- 권한 예외

-- Oracle은 업무 기록만 읽는다. 계정 비밀번호 해시와 토큰은 읽지 못하게 한다.
REVOKE ALL ON app_user, agent_token, user_session FROM oracle_ro;
