"""Application settings via pydantic-settings.

Reads from environment variables with FLOWABLE_ prefix and optional .env file.
"""

from pydantic import SecretStr, field_validator, model_validator
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

    # Diagram-specific settings (TASK-005, AC-S2-5, AC-4.6)
    diagram_max_png_bytes: int = 5_242_880   # env: FLOWABLE_DIAGRAM_MAX_PNG_BYTES (5 MiB)
    diagram_timeout_s: float = 30.0          # env: FLOWABLE_DIAGRAM_TIMEOUT_S
    diagram_max_concurrent: int = 4          # env: FLOWABLE_DIAGRAM_MAX_CONCURRENT

    @field_validator("base_url", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: object) -> str:
        return str(v).rstrip("/")

    @model_validator(mode="after")
    def _check_rss_budget(self) -> "Settings":
        """Ensures peak PNG RAM ≤ 50 MiB (AC-EDGE-10, I-9, RC-005-4)."""
        limit = 50 * 1024 * 1024  # 50 MiB
        peak = self.diagram_max_concurrent * self.diagram_max_png_bytes
        if peak > limit:
            raise ValueError(
                f"diagram_max_concurrent × diagram_max_png_bytes = {peak} "
                f"> {limit} bytes (50 MiB RSS budget)"
            )
        return self
