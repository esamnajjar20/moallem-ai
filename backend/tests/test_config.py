import os
from pathlib import Path

import pytest

from moallem.config import ConfigError, Environment, Settings, load_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in [k for k in os.environ if k.startswith("MOALLEM_")]:
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)  # avoid picking up a developer's .env


def test_development_needs_no_backing_services() -> None:
    s = load_settings()
    assert s.env is Environment.DEVELOPMENT
    assert s.database_url is None


def test_production_requires_database_and_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOALLEM_ENV", "production")
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
    s = Settings()
    assert "topsecret" not in repr(s)
    assert "topsecret" not in str(s.safe_summary())
    assert s.safe_summary()["database_url_set"] is True
