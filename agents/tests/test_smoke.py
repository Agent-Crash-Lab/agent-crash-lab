"""Local installation checks; no external LLM or MCP calls."""

from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agents.config import Settings
from agents.server import create_app


@pytest.mark.parametrize(
    "module_name",
    [
        "agents.graph",
        "agents.tools",
        "langgraph.graph",
        "langchain",
        "langchain_openai",
        "langchain_mcp_adapters.client",
        "mcp.client.session",
        "uvicorn",
    ],
)
def test_dependency_import(module_name: str) -> None:
    assert import_module(module_name) is not None


def test_health_without_external_services(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_URL", "http://mcp-server:8081/mcp")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    settings = Settings(_env_file=None)
    assert str(settings.mcp_url) == "http://mcp-server:8081/mcp"
    assert settings.llm_api_key.get_secret_value() == "test-key"
    assert settings.llm_model == "test-model"
    assert "test-key" not in repr(settings)


def test_settings_reject_invalid_mcp_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_URL", "invalid")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
