"""Environment settings shared by the future Agent implementations."""

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mcp_url: HttpUrl = HttpUrl("http://localhost:8081/mcp")
    llm_api_key: SecretStr = SecretStr("")
