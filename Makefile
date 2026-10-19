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
