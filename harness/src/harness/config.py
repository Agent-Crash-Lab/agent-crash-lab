"""Settings for the single-process Harness service."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///.harness-state/harness.sqlite"
    oracle_database_url: str = ""
    mcp_url: str = "http://localhost:8081"
    agent_url: str = "http://localhost:8090"
    internal_api_token: SecretStr = SecretStr("")
    harness_dev_auth: bool = False
    simulation_callback_base: str = "http://harness:8000"
    external_agent_endpoints: SecretStr = SecretStr("{}")
    harness_project_root: Path = Path(__file__).resolve().parents[3]
    poll_interval_seconds: float = 0.5
    # Agent enforces 600s itself; the Runner stops polling a little later.
    runner_deadline_seconds: float = 630
    finalize_wait_ms: int = 5000
    sse_keepalive_seconds: float = 15
    # Events wait this long before numbering so polled Agent events can catch up
    # with pushed MCP events (HARNESS_SPEC 2.9). Must exceed poll_interval_seconds.
    events_hold_seconds: float = 1.0


def sqlalchemy_url(url: str) -> str:
    # Compose passes libpq-style URLs; SQLAlchemy needs the psycopg driver name.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url
