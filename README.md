# Agent Crash Lab

AI Agent를 출시하기 전에 사고를 내보는 시험장.

시험용 업무 환경(DB와 MCP 도구)에 오류와 예외 상황을 주입하고, Agent가 승인 없는 변경, 중복 처리, 권한 우회 같은 잘못된 행동을 하는지 **DB 상태와 도구 호출 기록으로** 판정합니다.

## 레포 구조

```
agent-crash-lab/
├── contracts/     # 공통 계약 (JSON Schema, OpenAPI). 변경 시 전원 리뷰
├── mcp-server/    # MCP 서버, 가상 업무 환경 (Java / Spring AI)   — MCP 담당
├── agents/        # 시험 대상 Agent (Python)                     — Agent 담당
├── harness/       # 시나리오 실행, 판정, 재생, 보고서 (Python)     — Harness 담당
├── frontend/      # 대시보드
├── scenarios/     # 시나리오 정의 파일
├── fixtures/      # seed 데이터, 규정 문서
└── infra/
    ├── docker-compose.yml
    └── postgres/init.sql
```

## 실행

```bash
cp .env.example .env    # 처음 한 번
make up                 # 전체 빌드 후 기동
make db                 # Postgres 만 기동
make logs s=mcp-server  # 특정 서비스 로그
make down               # 중지
make clean              # 중지 + DB 초기화
```

`make` 가 없으면 아래 명령을 직접 실행하면 됩니다.

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
```

## 서비스

| 서비스 | 호스트 포트 | 컨테이너 내부 주소 |
|---|---|---|
| postgres | 5432 | `postgres:5432` |
| mcp-server | 8081 | `http://mcp-server:8081` (MCP: `/mcp`) |
| agents | 8090 | `http://agents:8090` |
| harness | 8000 | `http://harness:8000` |
| frontend | 5173 | - |

## 공통 규칙

- 모든 앱 서비스는 `GET /health` 를 제공합니다. compose 기동 순서가 이 헬스체크에 의존합니다.
- 각 서비스 폴더의 `Dockerfile` 은 기본 템플릿이니 담당자가 프로젝트에 맞게 수정하세요.
- 서비스 간 주소, DB 접속 정보, API 키는 환경변수로만 주입합니다 (`infra/docker-compose.yml` 참고).

### DB 계정

| 계정 | 사용처 | 권한 |
|---|---|---|
| `mcp_app` | mcp-server | `sandbox` 스키마 소유 |
| `harness_app` | harness | `harness` 스키마 소유 |
| `oracle_ro` | harness 판정 로직 | `sandbox` 스키마 읽기 전용 |
