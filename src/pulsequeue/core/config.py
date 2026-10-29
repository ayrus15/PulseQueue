"""Application configuration, read from environment variables.

See ``.env.example`` at the repository root for every variable this
settles reads and its intended default. Only the fields actually used by
the current implementation phase are consumed; the rest are declared now
so later phases don't need to touch this module's shape.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    databaseUrl: str = Field(
        default="postgresql+asyncpg://pulsequeue:change-me-locally@localhost:5432/pulsequeue",
        validation_alias="DATABASE_URL",
    )
    redisUrl: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )
    adminToken: str = Field(
        default="change-me-locally",
        validation_alias="PULSEQUEUE_ADMIN_TOKEN",
    )
    logLevel: str = Field(
        default="INFO",
        validation_alias="PULSEQUEUE_LOG_LEVEL",
    )
    allowedOrigins: str = Field(
        default="",
        validation_alias="PULSEQUEUE_ALLOWED_ORIGINS",
    )
    workerConcurrency: int = Field(
        default=4,
        ge=1,
        validation_alias="PULSEQUEUE_WORKER_CONCURRENCY",
    )
    workerLeaseSeconds: int = Field(
        default=30,
        ge=1,
        validation_alias="PULSEQUEUE_WORKER_LEASE_SECONDS",
    )
    workerPollIntervalSeconds: float = Field(
        default=1.0,
        gt=0,
        validation_alias="PULSEQUEUE_WORKER_POLL_INTERVAL_SECONDS",
    )
    defaultMaxAttempts: int = Field(
        default=4,
        ge=1,
        validation_alias="PULSEQUEUE_DEFAULT_MAX_ATTEMPTS",
    )
    retryBaseDelaySeconds: float = Field(
        default=1.0,
        gt=0,
        validation_alias="PULSEQUEUE_RETRY_BASE_DELAY_SECONDS",
    )
    retryMaxDelaySeconds: float = Field(
        default=60.0,
        gt=0,
        validation_alias="PULSEQUEUE_RETRY_MAX_DELAY_SECONDS",
    )
    processFileDirectory: str = Field(
        default="var/process_file_inbox",
        validation_alias="PULSEQUEUE_PROCESS_FILE_DIR",
    )
    """The only directory the processFile handler may ever read from -
    ADR 0003's "restrict file processing to a controlled directory"."""

    @property
    def allowedOriginsList(self) -> list[str]:
        return [origin.strip() for origin in self.allowedOrigins.split(",") if origin.strip()]


@lru_cache
def getSettings() -> Settings:
    """Return the process-wide Settings singleton.

    Cached so repeated calls (e.g. from FastAPI dependencies) don't re-read
    the environment on every request; tests that need different settings
    should construct ``Settings(...)`` directly instead of mutating this.
    """
    return Settings()
