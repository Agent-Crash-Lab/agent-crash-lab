COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

.PHONY: up down logs ps db clean

up:        ## 전체 서비스 빌드 후 기동
	$(COMPOSE) up -d --build

down:      ## 전체 서비스 중지
	$(COMPOSE) down

logs:      ## 로그 보기 (예: make logs s=mcp-server)
	$(COMPOSE) logs -f $(s)

ps:        ## 서비스 상태 확인
	$(COMPOSE) ps

db:        ## Postgres 만 기동
	$(COMPOSE) up -d postgres

clean:     ## 서비스 중지 + DB 볼륨 삭제 (init.sql 다시 실행됨)
	$(COMPOSE) down -v

# Isolated development volumes; choose mock, MCP, or Harness services.
COMPOSE_DEV = docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file .env

.PHONY: dev-check dev-up dev-mcp-up dev-harness-up dev-down dev-ps dev-logs agent-demo

dev-check: ## 개발용 Compose 설정 확인
	$(COMPOSE_DEV) config --quiet

dev-up: dev-check ## DB + Agent health + 정적 화면만 시작
	$(COMPOSE_DEV) up -d --build --wait --wait-timeout 90 postgres agents frontend

dev-mcp-up: dev-check ## 실제 MCP + DB + Agent + 정적 화면 시작 (Harness 제외)
	$(COMPOSE_DEV) up -d --build --wait --wait-timeout 120 postgres mcp-server agents frontend

dev-harness-up: dev-check ## 실제 Harness + MCP + DB + Agent + 프론트 시작
	$(COMPOSE_DEV) up -d --build --wait --wait-timeout 180 postgres mcp-server agents harness frontend

dev-down: ## 개발 컨테이너 종료 (DB 볼륨 보존)
	$(COMPOSE_DEV) down

dev-ps:
	$(COMPOSE_DEV) ps

dev-logs:
	$(COMPOSE_DEV) logs -f $(s)

agent-demo: ## 예: make agent-demo scenario=timeout-once
	$(COMPOSE_DEV) run --rm --no-deps agents uv run --no-sync python -m agents.demo --scenario $(or $(scenario),approved)


.PHONY: dev-rag-up knowledge-index
dev-rag-up: dev-check ## PostgreSQL 유지 → pgvector 준비 → 실제 BGE 색인 → 전체 개발 서비스
	python3 scripts/prepare_knowledge.py
	$(COMPOSE_DEV) up -d --build --wait postgres
	$(COMPOSE_DEV) exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < infra/postgres/knowledge.sql
	$(COMPOSE_DEV) build knowledge
	$(COMPOSE_DEV) run --rm --no-deps knowledge python -m knowledge.index
	$(COMPOSE_DEV) up -d --build --wait --wait-timeout 240 postgres knowledge mcp-server agents harness frontend

knowledge-index: ## 자료 변경 후 재색인. 동일 데이터·모델은 건너뜀
	$(COMPOSE_DEV) run --rm --no-deps knowledge python -m knowledge.index
