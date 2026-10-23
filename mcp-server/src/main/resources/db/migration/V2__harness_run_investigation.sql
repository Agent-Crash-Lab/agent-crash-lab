-- Harness 모의 환경(생산·품질) 실행도 조사 Agent가 읽을 수 있게 조사 전용으로 등록한다.
-- 업무 상태·도구 호출 원본은 Harness에 있고, 여기에는 토큰·조사 도구 호출 기록의 기준 행만 둔다.
ALTER TABLE run_context
    ADD COLUMN agent_type text NOT NULL DEFAULT 'PURCHASE'
        CHECK (agent_type IN ('PURCHASE', 'PRODUCTION', 'QUALITY'));

ALTER TABLE run_context DROP CONSTRAINT run_context_server_policy_version_check;
ALTER TABLE run_context ADD CONSTRAINT run_context_server_policy_version_check
    CHECK (server_policy_version IN ('baseline-v1', 'idempotent-v1', 'harness-sandbox'));
