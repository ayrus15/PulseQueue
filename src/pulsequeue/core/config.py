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
    rateLimitEnabled: bool = Field(
        default=False,
        validation_alias="PULSEQUEUE_RATE_LIMIT_ENABLED",
    )
    """Off by default - a demo/local deployment, not an exposed service.
    See api/rateLimit.py."""
    rateLimitPerMinute: int = Field(
        default=120,
        ge=1,
        validation_alias="PULSEQUEUE_RATE_LIMIT_PER_MINUTE",
    )
    dbConnectTimeoutSeconds: float = Field(
        default=10.0,
        gt=0,
        validation_alias="PULSEQUEUE_DB_CONNECT_TIMEOUT_SECONDS",
    )
    dbCommandTimeoutSeconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias="PULSEQUEUE_DB_COMMAND_TIMEOUT_SECONDS",
    )
    """Per-query timeout (asyncpg's ``command_timeout``) - a single stuck
    query can never block a connection forever."""
    dbPoolTimeoutSeconds: float = Field(
        default=10.0,
        gt=0,
        validation_alias="PULSEQUEUE_DB_POOL_TIMEOUT_SECONDS",
    )
    """How long to wait for a free connection from the pool before
    raising, rather than queuing indefinitely under load."""
    redisConnectTimeoutSeconds: float = Field(
        default=5.0,
        gt=0,
        validation_alias="PULSEQUEUE_REDIS_CONNECT_TIMEOUT_SECONDS",
    )
    """Only bounds establishing the TCP connection - deliberately not a
    blanket per-command socket timeout, since BLPOP's own `timeout`
    argument (waitForNotification) intentionally blocks for several
    seconds at a time; a client-wide read timeout shorter than that
    would misreport a normal wait as a connection failure."""
    taskExecutionTimeoutSeconds: float = Field(
        default=60.0,
        gt=0,
        validation_alias="PULSEQUEUE_TASK_EXECUTION_TIMEOUT_SECONDS",
    )
    """A handler that runs longer than this is cancelled and treated as a
    retryable failure - without this, a single hung handler invocation
    would occupy that worker slot forever (ADR 0003's lease is a
    *different* safety net: it protects against a dead *worker*, not a
    live worker stuck inside one handler call)."""
    apiRequestTimeoutSeconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias="PULSEQUEUE_API_REQUEST_TIMEOUT_SECONDS",
    )
    maxRequestBodyBytes: int = Field(
        default=1_000_000,
        gt=0,
        validation_alias="PULSEQUEUE_MAX_REQUEST_BODY_BYTES",
    )
    """Rejects a request whose declared Content-Length exceeds this with
    413 before the body is read - every real payload field already has
    its own max_length, so 1 MB comfortably covers any legitimate
    submission while still bounding how much a client can make the
    server buffer before that per-field validation ever runs."""

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
