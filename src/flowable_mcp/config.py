"""Application settings via pydantic-settings.

Reads from environment variables with FLOWABLE_ prefix and optional .env file.
"""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLOWABLE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Trailing slash stripped by validator (Invariant I4).
    # Includes /service path segment — Flowable REST API base.
    base_url: str = "http://localhost:8080/flowable-rest/service"
    username: str = "rest-admin"
    password: SecretStr  # required; set FLOWABLE_PASSWORD env var
    timeout_s: float = 10.0
    # Total request attempts (1 = no retry). Transport uses retries = retry_attempts - 1.
    retry_attempts: int = 2

    @field_validator("base_url", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: object) -> str:
        return str(v).rstrip("/")
