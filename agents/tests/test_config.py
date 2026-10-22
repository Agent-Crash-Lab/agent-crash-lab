"""Environment settings and invalid configuration checks."""

import pytest
from pydantic import ValidationError

from agents.config import Settings


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
