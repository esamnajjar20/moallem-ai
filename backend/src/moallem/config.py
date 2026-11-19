"""Typed, fail-fast configuration (P1-03).

Rules:
- No invented defaults for anything environment-specific (DB/Redis URLs, budgets).
- Secrets are SecretStr and never appear in repr, logs, or error output.
- Startup aborts with a ConfigError that lists field names only, never values.
"""

import base64
import binascii
import ipaddress
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


class PermissionPolicyName(StrEnum):
    DENY_ALL = "deny_all"
    TEACHER_MVP = "teacher_mvp"  # DEC-027 approved Teacher MVP matrix


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
    # Fail-closed default. "teacher_mvp" enables the approved DEC-027 matrix for the API.
    permission_policy: PermissionPolicyName = PermissionPolicyName.DENY_ALL
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    readiness_timeout_seconds: float = 2.0
    auth_issuer: str | None = None  # Exact Auth0 OIDC issuer, including trailing slash
    auth_audience: str | None = None  # Exact Auth0 API identifier
    auth_max_token_lifetime_seconds: int | None = None  # MVP access-token ceiling: 15 minutes
    # Optional, explicitly pinned AI provider configuration. It registers a transport only;
    # it never authorizes model execution. ADR-018/DEC-043 remain separate gates.
    ai_provider_id: str | None = None
    ai_model_id: str | None = None
    ai_model_version: str | None = None
    ai_region: str | None = None
    ai_base_url: str | None = None
    ai_api_key: SecretStr | None = None
    ai_allowed_hosts: tuple[str, ...] | None = None
    ai_timeout_seconds: float = 60.0
    ai_max_request_bytes: int = 2 * 1024 * 1024
    ai_max_response_bytes: int = 2 * 1024 * 1024
    secret_encryption_key: SecretStr | None = None
    idempotency_hmac_key: SecretStr | None = None
    idempotency_retention_seconds: int | None = None
    approval_ttl_seconds: int | None = None
    event_cursor_hmac_key: SecretStr | None = None
    task_queue_poll_seconds: float | None = None
    task_queue_batch_size: int | None = None
    task_queue_lease_seconds: int | None = None
    task_queue_lease_renew_seconds: int | None = None
    task_queue_max_attempts: int | None = None
    task_queue_retry_base_seconds: int | None = None
    task_queue_retry_max_seconds: int | None = None
    task_queue_shutdown_grace_seconds: int | None = None
    task_queue_idempotency_cleanup_interval_seconds: int | None = None
    task_queue_idempotency_cleanup_batch_size: int | None = None

    @field_validator("readiness_timeout_seconds")
    @classmethod
    def _timeout_range(cls, v: float) -> float:
        if not 0 < v <= 10:
            raise ValueError("must be > 0 and <= 10")
        return v

    @field_validator("ai_allowed_hosts")
    @classmethod
    def _ai_allowed_hosts(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        if not value or len(value) > 16:
            raise ValueError("ai_allowed_hosts must contain 1..16 exact hostnames")
        normalized: list[str] = []
        for host in value:
            if not isinstance(host, str) or not host or host != host.strip():
                raise ValueError("ai_allowed_hosts entries must be exact hostnames")
            candidate = host.rstrip(".").encode("idna").decode("ascii").lower()
            if (
                not candidate
                or "*" in candidate
                or "/" in candidate
                or ":" in candidate
                or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in candidate)
            ):
                raise ValueError("ai_allowed_hosts entries must be exact DNS hostnames")
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                pass
            else:
                raise ValueError("ai_allowed_hosts must use DNS hostnames, not IP literals")
            if candidate in normalized:
                raise ValueError("ai_allowed_hosts must not contain duplicates")
            normalized.append(candidate)
        return tuple(normalized)

    @field_validator("ai_timeout_seconds")
    @classmethod
    def _ai_timeout(cls, value: float) -> float:
        if not 0 < value <= 300:
            raise ValueError("ai_timeout_seconds must be > 0 and <= 300")
        return value

    @field_validator("ai_max_request_bytes", "ai_max_response_bytes")
    @classmethod
    def _ai_payload_limit(cls, value: int, info: ValidationInfo) -> int:
        if not 1024 <= value <= 16 * 1024 * 1024:
            raise ValueError(f"{info.field_name} must be 1KiB..16MiB")
        return value

    @field_validator("approval_ttl_seconds")
    @classmethod
    def _approval_ttl(cls, value: int | None) -> int | None:
        if value is not None and not 60 <= value <= 86_400:
            raise ValueError("approval_ttl_seconds must be between 60 and 86400")
        return value

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
        if self.auth_issuer is not None:
            issuer = urlsplit(self.auth_issuer)
            if (
                issuer.scheme != "https"
                or not issuer.hostname
                or issuer.username is not None
                or issuer.password is not None
                or issuer.query
                or issuer.fragment
                or issuer.path not in ("", "/")
                or not self.auth_issuer.endswith("/")
            ):
                raise ValueError(
                    "auth_issuer must be an exact HTTPS issuer URL ending in /"
                )
        if self.auth_audience is not None and (
            not self.auth_audience.strip()
            or self.auth_audience != self.auth_audience.strip()
            or len(self.auth_audience) > 512
        ):
            raise ValueError("auth_audience must be a non-empty exact API identifier")
        lifetime = self.auth_max_token_lifetime_seconds
        if lifetime is not None and not 60 <= lifetime <= 900:
            raise ValueError("auth_max_token_lifetime_seconds must be 60..900 for the MVP")
        if self.env in (Environment.STAGING, Environment.PRODUCTION) and self.auth_issuer is None:
            raise ValueError(
                "Auth0 issuer, audience and token lifetime are required outside dev/test"
            )
        return self

    @model_validator(mode="after")
    def _ai_provider_settings(self) -> Self:
        identity_and_transport = (
            self.ai_provider_id,
            self.ai_model_id,
            self.ai_model_version,
            self.ai_region,
            self.ai_base_url,
            self.ai_api_key,
            self.ai_allowed_hosts,
        )
        if any(value is not None for value in identity_and_transport) and not all(
            value is not None for value in identity_and_transport
        ):
            raise ValueError(
                "AI provider settings require provider/model/version/region/base URL/API key/allowed hosts"
            )
        if self.ai_provider_id is not None:
            for name, value, max_length in (
                ("ai_provider_id", self.ai_provider_id, 128),
                ("ai_model_id", self.ai_model_id, 255),
                ("ai_model_version", self.ai_model_version, 128),
                ("ai_region", self.ai_region, 64),
            ):
                if value is None or not value or value != value.strip() or len(value) > max_length:
                    raise ValueError(f"{name} must be 1..{max_length} trimmed characters")
            if self.ai_model_version is not None and self.ai_model_version.casefold() in {
                "latest", "stable", "default", "current"
            }:
                raise ValueError("ai_model_version must identify a pinned revision, not an alias")
            assert self.ai_base_url is not None  # noqa: S101
            assert self.ai_allowed_hosts is not None  # noqa: S101
            parsed = urlsplit(self.ai_base_url)
            if (
                parsed.scheme.lower() != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or "\\" in self.ai_base_url
                or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in self.ai_base_url)
            ):
                raise ValueError("ai_base_url must be an absolute HTTPS URL without credentials")
            host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
            if host not in self.ai_allowed_hosts:
                raise ValueError("ai_base_url hostname must exactly match ai_allowed_hosts")
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
    def _p4_queue_settings(self) -> Self:
        if self.task_queue_poll_seconds is not None and self.task_queue_poll_seconds <= 0:
            raise ValueError("task_queue_poll_seconds must be positive")
        if self.task_queue_batch_size is not None and self.task_queue_batch_size < 1:
            raise ValueError("task_queue_batch_size must be positive")
        if self.task_queue_lease_seconds is not None and self.task_queue_lease_seconds < 1:
            raise ValueError("task_queue_lease_seconds must be positive")
        if (
            self.task_queue_lease_renew_seconds is not None
            and self.task_queue_lease_renew_seconds < 1
        ):
            raise ValueError("task_queue_lease_renew_seconds must be positive")
        if (
            self.task_queue_lease_renew_seconds is not None
            and self.task_queue_lease_seconds is not None
            and self.task_queue_lease_renew_seconds >= self.task_queue_lease_seconds
        ):
            raise ValueError("task_queue_lease_renew_seconds must be less than the lease")
        if (
            self.task_queue_shutdown_grace_seconds is not None
            and self.task_queue_shutdown_grace_seconds < 0
        ):
            raise ValueError("task_queue_shutdown_grace_seconds must not be negative")
        if (
            self.task_queue_idempotency_cleanup_interval_seconds is not None
            and self.task_queue_idempotency_cleanup_interval_seconds < 1
        ):
            raise ValueError("task_queue_idempotency_cleanup_interval_seconds must be positive")
        if (
            self.task_queue_idempotency_cleanup_batch_size is not None
            and self.task_queue_idempotency_cleanup_batch_size < 1
        ):
            raise ValueError("task_queue_idempotency_cleanup_batch_size must be positive")
        queue_values = (
            self.task_queue_poll_seconds,
            self.task_queue_batch_size,
            self.task_queue_lease_seconds,
            self.task_queue_lease_renew_seconds,
            self.task_queue_shutdown_grace_seconds,
            self.task_queue_max_attempts,
            self.task_queue_retry_base_seconds,
            self.task_queue_retry_max_seconds,
            self.task_queue_idempotency_cleanup_interval_seconds,
            self.task_queue_idempotency_cleanup_batch_size,
        )
        retry_values = (
            self.task_queue_max_attempts,
            self.task_queue_retry_base_seconds,
            self.task_queue_retry_max_seconds,
        )
        if any(value is not None for value in retry_values) and not all(
            value is not None for value in retry_values
        ):
            raise ValueError("all task queue retry settings must be set together")
        if all(value is not None for value in retry_values):
            assert self.task_queue_max_attempts is not None  # noqa: S101
            assert self.task_queue_retry_base_seconds is not None  # noqa: S101
            assert self.task_queue_retry_max_seconds is not None  # noqa: S101
            if self.task_queue_max_attempts < 1:
                raise ValueError("task_queue_max_attempts must be positive")
            if self.task_queue_retry_base_seconds < 1:
                raise ValueError("task_queue_retry_base_seconds must be positive")
            if self.task_queue_retry_max_seconds < self.task_queue_retry_base_seconds:
                raise ValueError("task_queue_retry_max_seconds must be >= retry base")
        if self.env in (Environment.STAGING, Environment.PRODUCTION) and any(
            value is None for value in queue_values
        ):
            raise ValueError("all task queue settings are required outside dev/test")
        return self

    @model_validator(mode="after")
    def _require_backing_services_outside_dev(self) -> Self:
        if self.env in (Environment.STAGING, Environment.PRODUCTION):
            missing = [
                name
                for name, value in (
                    ("database_url", self.database_url),
                    ("idempotency_hmac_key", self.idempotency_hmac_key),
                    ("idempotency_retention_seconds", self.idempotency_retention_seconds),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"required in {self.env.value}: {', '.join(missing)}")
        return self

    def safe_summary(self) -> dict[str, str | int | float | bool | None]:
        """Loggable view: no secret values, only whether they are set."""
        return {
            "env": self.env.value,
            "log_level": self.log_level.value,
            "database_url_set": self.database_url is not None,
            "redis_url_set": self.redis_url is not None,
            "readiness_timeout_seconds": self.readiness_timeout_seconds,
            "auth_configured": self.auth_issuer is not None,
            "ai_provider_configured": self.ai_provider_id is not None,
            "ai_api_key_set": self.ai_api_key is not None,
            "secret_encryption_key_set": self.secret_encryption_key is not None,
            "idempotency_configured": self.idempotency_hmac_key is not None,
            "approval_policy_configured": self.approval_ttl_seconds is not None,
            "event_cursor_configured": self.event_cursor_hmac_key is not None,
            "task_queue_poll_seconds": self.task_queue_poll_seconds,
            "task_queue_batch_size": self.task_queue_batch_size,
            "task_queue_lease_seconds": self.task_queue_lease_seconds,
            "task_queue_lease_renew_seconds": self.task_queue_lease_renew_seconds,
            "task_queue_max_attempts_set": self.task_queue_max_attempts is not None,
            "task_queue_shutdown_grace_seconds": self.task_queue_shutdown_grace_seconds,
            "task_queue_idempotency_cleanup_interval_seconds": (
                self.task_queue_idempotency_cleanup_interval_seconds
            ),
            "task_queue_idempotency_cleanup_batch_size": (
                self.task_queue_idempotency_cleanup_batch_size
            ),
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
