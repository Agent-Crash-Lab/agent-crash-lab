FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /uvx /bin/
WORKDIR /app
COPY . .
RUN uv sync --locked --no-dev
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "--no-dev", "uvicorn", "harness.api:app", "--host", "0.0.0.0", "--port", "8000"]
