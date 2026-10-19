"""Minimal service entry point matching the repository's Compose contract."""

from fastapi import FastAPI

app = FastAPI(title="Agent Crash Lab — Agents")


@app.get("/health")
def health() -> dict[str, str]:
    """Report process availability; this does not check MCP or LLM readiness."""
    return {"status": "ok"}
