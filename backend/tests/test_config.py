import base64
import os
from pathlib import Path

import pytest

from moallem.config import ConfigError, Environment, Settings, load_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in [key for key in os.environ if key.startswith("MOALLEM_")]:
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


def _set_production_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_AUTH_ISSUER", "https://tenant.auth0.com/")
    monkeypatch.setenv("MOALLEM_AUTH_AUDIENCE", "moallem-api")
    monkeypatch.setenv("MOALLEM_AUTH_MAX_TOKEN_LIFETIME_SECONDS", "900")
    monkeypatch.setenv("MOALLEM_IDEMPOTENCY_HMAC_KEY", base64.b64encode(b"i" * 32).decode())
    monkeypatch.setenv("MOALLEM_IDEMPOTENCY_RETENTION_SECONDS", "86400")
    monkeypatch.setenv("MOALLEM_EVENT_CURSOR_HMAC_KEY", base64.b64encode(b"e" * 32).decode())


def test_development_needs_no_backing_services() -> None:
    settings = load_settings()
    assert settings.env is Environment.DEVELOPMENT
    assert settings.database_url is None


def test_production_requires_backing_services(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_ENV", "production")
    _set_production_auth(monkeypatch)
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "database_url" in str(exc.value)
    assert "redis_url" in str(exc.value)


def test_invalid_values_fail_fast_without_echoing_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_DATABASE_URL", "mysql://user:topsecret@h/db")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "topsecret" not in str(exc.value)


def test_timeout_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_READINESS_TIMEOUT_SECONDS", "0")
    with pytest.raises(ConfigError):
        load_settings()


def test_secrets_never_appear_in_repr_or_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_DATABASE_URL", "postgresql://u:topsecret@db/x")
    monkeypatch.setenv("MOALLEM_REDIS_URL", "redis://:topsecret@cache/0")
    settings = Settings()
    assert "topsecret" not in repr(settings)
    assert "topsecret" not in str(settings.safe_summary())
    assert settings.safe_summary()["database_url_set"] is True


def test_auth_settings_are_all_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_AUTH_ISSUER", "https://t.auth0.com/")
    with pytest.raises(ConfigError):
        load_settings()
    monkeypatch.setenv("MOALLEM_AUTH_AUDIENCE", "api")
    monkeypatch.setenv("MOALLEM_AUTH_MAX_TOKEN_LIFETIME_SECONDS", "900")
    assert load_settings().safe_summary()["auth_configured"] is True


def test_auth_issuer_must_be_https_and_lifetime_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_AUTH_ISSUER", "http://t.auth0.com/")
    monkeypatch.setenv("MOALLEM_AUTH_AUDIENCE", "api")
    monkeypatch.setenv("MOALLEM_AUTH_MAX_TOKEN_LIFETIME_SECONDS", "900")
    with pytest.raises(ConfigError):
        load_settings()
    monkeypatch.setenv("MOALLEM_AUTH_ISSUER", "https://t.auth0.com/")
    monkeypatch.setenv("MOALLEM_AUTH_MAX_TOKEN_LIFETIME_SECONDS", "5")
    with pytest.raises(ConfigError):
        load_settings()


def test_staging_requires_auth0_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_ENV", "staging")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "Auth0 issuer" in str(exc.value)


def test_encryption_key_must_be_a_32_byte_base64_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = base64.b64encode(b"x" * 32).decode()
    monkeypatch.setenv("MOALLEM_SECRET_ENCRYPTION_KEY", encoded)
    settings = load_settings()
    assert settings.safe_summary()["secret_encryption_key_set"] is True
    assert "x" * 32 not in repr(settings)
    monkeypatch.setenv("MOALLEM_SECRET_ENCRYPTION_KEY", base64.b64encode(b"short").decode())
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "32 bytes" in str(exc.value)


def test_environment_encryption_key_is_rejected_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOALLEM_ENV", "staging")
    _set_production_auth(monkeypatch)
    monkeypatch.setenv("MOALLEM_SECRET_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "development-only" in str(exc.value)


def test_idempotency_configuration_requires_key_and_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOALLEM_IDEMPOTENCY_HMAC_KEY", base64.b64encode(b"x" * 32).decode())
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "must be set together" in str(exc.value)
