from fastapi import FastAPI
from fastapi.testclient import TestClient

from moallem.api.app import create_app
from moallem.config import Settings
from moallem.health.checks import CheckResult


def _settings() -> Settings:
    return Settings(env="test", _env_file=None)


def _ok() -> object:
    async def check() -> CheckResult:
        return CheckResult("postgres", True, "tcp_reachable")

    return check


def _down() -> object:
    async def check() -> CheckResult:
        return CheckResult("redis", False, "unreachable")

    return check


def test_liveness_ok_and_never_checks_dependencies() -> None:
    app = create_app(_settings(), checks=[_down()])  # type: ignore[list-item]
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_200_when_all_checks_pass() -> None:
    app = create_app(_settings(), checks=[_ok()])  # type: ignore[list-item]
    r = TestClient(app).get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"postgres": "ok"}}


def test_readiness_503_when_any_check_fails() -> None:
    app = create_app(_settings(), checks=[_ok(), _down()])  # type: ignore[list-item]
    r = TestClient(app).get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["redis"] == "unreachable"


def test_request_id_is_echoed_when_valid_and_regenerated_when_not() -> None:
    client = TestClient(create_app(_settings(), checks=[]))
    echoed = client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["X-Request-ID"] == "abc-123"
    regenerated = client.get("/healthz", headers={"X-Request-ID": "bad id!"})
    assert regenerated.headers["X-Request-ID"].startswith("req_")


def test_unknown_route_returns_error_envelope() -> None:
    r = TestClient(create_app(_settings(), checks=[])).get("/nope")
    body = r.json()
    assert r.status_code == 404
    assert body["code"] == "RESOURCE_NOT_FOUND"
    assert body["request_id"] == r.headers["X-Request-ID"]
    assert body["retryable"] is False


def test_validation_error_envelope_has_field_names_but_no_values() -> None:
    app: FastAPI = create_app(_settings(), checks=[])

    @app.get("/_t/validate")
    async def _validate(n: int) -> dict[str, int]:
        return {"n": n}

    r = TestClient(app).get("/_t/validate", params={"n": "super-secret-value"})
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_FAILED"
    assert "super-secret-value" not in r.text
    assert r.json()["details"]["field_errors"][0]["field"] == "query.n"


def test_unhandled_exception_returns_500_envelope_without_exception_text() -> None:
    app: FastAPI = create_app(_settings(), checks=[])

    @app.get("/_t/boom")
    async def _boom() -> None:
        raise RuntimeError("db password is hunter2")

    r = TestClient(app, raise_server_exceptions=False).get("/_t/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in r.text
    assert r.headers["X-Request-ID"] == r.json()["request_id"]


def test_docs_disabled_in_production() -> None:
    s = Settings(
        env="production",
        database_url="postgresql://u:p@db/x",
        redis_url="redis://cache/0",
        auth_issuer="https://tenant.example.auth0.com/",
        auth_audience="https://api.example",
        auth_max_token_lifetime_seconds=900,
        idempotency_hmac_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
        idempotency_retention_seconds=86400,
        event_cursor_hmac_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
        task_queue_poll_seconds=1,
        task_queue_batch_size=16,
        task_queue_lease_seconds=60,
        task_queue_lease_renew_seconds=20,
        task_queue_max_attempts=5,
        task_queue_retry_base_seconds=1,
        task_queue_retry_max_seconds=300,
        task_queue_shutdown_grace_seconds=30,
        task_queue_idempotency_cleanup_interval_seconds=300,
        task_queue_idempotency_cleanup_batch_size=100,
        _env_file=None,
    )
    client = TestClient(create_app(s, checks=[]))
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
