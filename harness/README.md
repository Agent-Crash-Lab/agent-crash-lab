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

## 환경변수

| 변수 | 용도 |
|---|---|
| `DATABASE_URL` | 실행·이벤트 기록 (harness_app) |
| `ORACLE_DATABASE_URL` | Oracle 업무 DB 조회 (oracle_ro) |
| `MCP_URL` | mcp-server 주소 (`http://mcp-server:8081`) |
| `AGENT_URL` | Agent 주소 (`http://agents:8090`) |
| `INTERNAL_API_TOKEN` | 내부 API 공유 토큰. 비어 있으면 Harness API는 503 |
| `HARNESS_DEV_AUTH` | 개발용 인증 우회 (기본 `false`) |
| `HARNESS_PROJECT_ROOT` | 공유 자료 위치 |
