# 기본 템플릿: uv 로 관리하는 Python 프로젝트와 harness.api:app (ASGI) 진입점을 가정한다.
# 담당자가 필요에 맞게 수정.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/
WORKDIR /app
COPY . .
RUN uv sync --no-dev
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "harness.api:app", "--host", "0.0.0.0", "--port", "8000"]
