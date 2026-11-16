"""Typed, fail-fast configuration (P1-03).

Rules:
- No invented defaults for anything environment-specific (DB/Redis URLs, budgets).
- Secrets are SecretStr and never appear in repr, logs, or error output.
- Startup aborts with a ConfigError that lists field names only, never values.
"""

import base64
import binascii
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import SecretStr, ValidationError, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ConfigError(RuntimeError):
    """Raised on invalid configuration. Message contains field names only."""


_DB_SCHEMES = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
_REDIS_SCHEMES = {"redis", "rediss"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOALLEM_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    env: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    readiness_timeout_seconds: float = 2.0
    auth_issuer: str | None = None  # Auth0 issuer URL; keep trailing slash
    auth_audience: str | None = None  # Auth0 API identifier
    auth_max_token_lifetime_seconds: int | None = None
    secret_encryption_key: SecretStr | None = None
    idempotency_hmac_key: SecretStr | None = None
    idempotency_retention_seconds: int | None = None
    event_cursor_hmac_key: SecretStr | None = None

    @field_validator("readiness_timeout_seconds")
    @classmethod
    def _timeout_range(cls, v: float) -> float:
        if not 0 < v <= 10:
            raise ValueError("must be > 0 and <= 10")
        return v

    @field_validator("database_url")
    @classmethod
    def _db_scheme(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None and urlsplit(v.get_secret_value()).scheme not in _DB_SCHEMES:
            raise ValueError("unsupported database URL scheme")
        return v

    @field_validator("redis_url")
    @classmethod
    def _redis_scheme(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None and urlsplit(v.get_secret_value()).scheme not in _REDIS_SCHEMES:
            raise ValueError("unsupported redis URL scheme")
        return v

    @field_validator("secret_encryption_key", "idempotency_hmac_key", "event_cursor_hmac_key")
    @classmethod
    def _base64_key(cls, v: SecretStr | None, info: ValidationInfo) -> SecretStr | None:
        if v is None:
            return None
        try:
            key = base64.b64decode(v.get_secret_value(), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"{info.field_name} must be base64 encoded") from exc
        minimum = 32
        expected = 32 if info.field_name == "secret_encryption_key" else None
        if len(key) < minimum or (expected is not None and len(key) != expected):
            qualifier = "exactly 32" if expected is not None else "at least 32"
            raise ValueError(f"{info.field_name} must decode to {qualifier} bytes")
        return v

    @model_validator(mode="after")
    def _auth_all_or_none(self) -> Self:
        fields = (self.auth_issuer, self.auth_audience, self.auth_max_token_lifetime_seconds)
        if any(v is not None for v in fields) and not all(v is not None for v in fields):
            raise ValueError(
                "auth_issuer, auth_audience and auth_max_token_lifetime_seconds go together"
            )
        if self.auth_issuer is not None and urlsplit(self.auth_issuer).scheme != "https":
            raise ValueError("auth_issuer must be an https URL")
        lifetime = self.auth_max_token_lifetime_seconds
        if lifetime is not None and not 60 <= lifetime <= 86400:
            raise ValueError("auth_max_token_lifetime_seconds must be 60..86400")
        if self.env in (Environment.STAGING, Environment.PRODUCTION) and self.auth_issuer is None:
            raise ValueError(
                "Auth0 issuer, audience and token lifetime are required outside dev/test"
            )
        return self

    @model_validator(mode="after")
    def _p4_key_settings(self) -> Self:
        idempotency_values = (self.idempotency_hmac_key, self.idempotency_retention_seconds)
        if any(value is not None for value in idempotency_values) and not all(
            value is not None for value in idempotency_values
        ):
            raise ValueError(
                "idempotency_hmac_key and idempotency_retention_seconds must be set together"
            )
        if (
            self.idempotency_retention_seconds is not None
            and self.idempotency_retention_seconds < 1
        ):
            raise ValueError("idempotency_retention_seconds must be positive")
        if (
            self.env in (Environment.STAGING, Environment.PRODUCTION)
            and self.secret_encryption_key is not None
        ):
            raise ValueError("environment encryption keys are development-only; configure a KMS")
        if (
            self.env in (Environment.STAGING, Environment.PRODUCTION)
            and self.event_cursor_hmac_key is None
        ):
            raise ValueError("event cursor signing key is required outside dev/test")
        return self

    @model_validator(mode="after")
    def _require_backing_services_outside_dev(self) -> Self:
        if self.env in (Environment.STAGING, Environment.PRODUCTION):
            missing = [
                name
                for name, value in (
                    ("database_url", self.database_url),
                    ("redis_url", self.redis_url),
                    ("idempotency_hmac_key", self.idempotency_hmac_key),
                    ("idempotency_retention_seconds", self.idempotency_retention_seconds),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"required in {self.env.value}: {', '.join(missing)}")
        return self

    def safe_summary(self) -> dict[str, str | float | bool]:
        """Loggable view: no secret values, only whether they are set."""
        return {
            "env": self.env.value,
            "log_level": self.log_level.value,
            "database_url_set": self.database_url is not None,
            "redis_url_set": self.redis_url is not None,
            "readiness_timeout_seconds": self.readiness_timeout_seconds,
            "auth_configured": self.auth_issuer is not None,
            "secret_encryption_key_set": self.secret_encryption_key is not None,
            "idempotency_configured": self.idempotency_hmac_key is not None,
            "event_cursor_configured": self.event_cursor_hmac_key is not None,
        }


def load_settings() -> Settings:
    """Load settings or raise ConfigError (field names/messages only; no input values)."""
    try:
        return Settings()
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(p) for p in e['loc']) or 'settings'}: {e['msg']}" for e in exc.errors()
        ]
        raise ConfigError("invalid configuration: " + "; ".join(problems)) from None
