-- 최초 기동 시 1회 실행된다 (pgdata 볼륨이 비어 있을 때만).
-- 비밀번호는 docker-compose 가 넘겨준 환경변수에서 읽는다.

\getenv mcp_password MCP_DB_PASSWORD
\getenv harness_password HARNESS_DB_PASSWORD
\getenv oracle_password ORACLE_DB_PASSWORD

-- mcp_app     : mcp-server 전용. sandbox 스키마(가상 업무 환경) 소유
-- harness_app : harness 전용. harness 스키마(실행 기록, 보고서) 소유
-- oracle_ro   : 판정 로직 전용. sandbox 스키마 읽기 전용
CREATE ROLE mcp_app LOGIN PASSWORD :'mcp_password';
CREATE ROLE harness_app LOGIN PASSWORD :'harness_password';
CREATE ROLE oracle_ro LOGIN PASSWORD :'oracle_password';

CREATE SCHEMA sandbox AUTHORIZATION mcp_app;
CREATE SCHEMA harness AUTHORIZATION harness_app;

ALTER ROLE mcp_app SET search_path = sandbox;
ALTER ROLE harness_app SET search_path = harness;
ALTER ROLE oracle_ro SET search_path = sandbox;

-- mcp_app 이 앞으로 만드는 테이블도 oracle_ro 가 읽을 수 있게 한다
GRANT USAGE ON SCHEMA sandbox TO oracle_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE mcp_app IN SCHEMA sandbox
    GRANT SELECT ON TABLES TO oracle_ro;
ALTER ROLE oracle_ro SET default_transaction_read_only = on;
