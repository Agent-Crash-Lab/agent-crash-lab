"""Settings for a single-process development Agent service."""

from pathlib import Path

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mcp_url: HttpUrl = HttpUrl("http://localhost:8081/mcp")
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    internal_api_token: SecretStr = SecretStr("")
    agent_state_dir: Path = Path(".agent-state")
    agent_project_root: Path = Path(__file__).resolve().parents[3]


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {
            key: redact(item, secrets)
            for key, item in value.items()
            if not any(word in key.lower() for word in ("token", "api_key", "authorization"))
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value
