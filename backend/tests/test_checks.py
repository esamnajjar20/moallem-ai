import asyncio

import pytest

from moallem.health.checks import CheckResult, endpoint_of, run_checks, tcp_reachable


def test_endpoint_of_uses_defaults_and_explicit_ports() -> None:
    assert endpoint_of("postgresql://u:p@db/x") == ("db", 5432)
    assert endpoint_of("postgresql+asyncpg://u:p@db:6543/x") == ("db", 6543)
    assert endpoint_of("rediss://cache") == ("cache", 6379)


def test_endpoint_of_rejects_hostless_url() -> None:
    with pytest.raises(ValueError):
        endpoint_of("postgresql:///x")


async def _reachable_and_closed() -> tuple[CheckResult, CheckResult]:
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        up = await tcp_reachable("svc", "127.0.0.1", port, 1.0)
    down = await tcp_reachable("svc", "127.0.0.1", port, 1.0)  # server now closed
    return up, down


def test_tcp_reachable_reports_up_and_down_without_leaking_details() -> None:
    up, down = asyncio.run(_reachable_and_closed())
    assert up.ok is True
    assert down.ok is False
    assert "127.0.0.1" not in down.detail


def test_run_checks_survives_a_crashing_check() -> None:
    async def boom() -> CheckResult:
        raise RuntimeError("secret detail")

    results = asyncio.run(run_checks([boom]))
    assert results == [CheckResult("unknown", False, "check_error")]
