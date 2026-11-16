"""Readiness checks. Stdlib only.

P1 scope is TCP *reachability* of PostgreSQL and Redis. It does not prove authentication,
schema state, or query ability; real DB/Redis probes arrive with P2/P4 once drivers are chosen.
Check details are deliberately generic: they never include hosts, URLs, or exception text.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"postgresql": 5432, "redis": 6379, "rediss": 6379}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


Check = Callable[[], Awaitable[CheckResult]]


def endpoint_of(url: str) -> tuple[str, int]:
    """Extract (host, port) from a DB/Redis URL. Raises ValueError if it has no host."""
    parts = urlsplit(url)
    if not parts.hostname:
        raise ValueError("URL has no host")
    scheme = parts.scheme.split("+")[0]
    port = parts.port or _DEFAULT_PORTS.get(scheme)
    if port is None:
        raise ValueError("no port and no default for scheme")
    return parts.hostname, port


async def tcp_reachable(name: str, host: str, port: int, timeout_seconds: float) -> CheckResult:
    try:
        async with asyncio.timeout(timeout_seconds):
            _reader, writer = await asyncio.open_connection(host, port)
    except (OSError, TimeoutError):
        return CheckResult(name, False, "unreachable")
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return CheckResult(name, True, "tcp_reachable")


def tcp_check(name: str, url: str, timeout: float) -> Check:
    host, port = endpoint_of(url)

    async def _check() -> CheckResult:
        return await tcp_reachable(name, host, port, timeout)

    return _check


async def run_checks(checks: Sequence[Check]) -> list[CheckResult]:
    async def _safe(check: Check) -> CheckResult:
        try:
            return await check()
        except Exception:  # a failing check must never crash readiness
            return CheckResult("unknown", False, "check_error")

    return list(await asyncio.gather(*(_safe(c) for c in checks)))
