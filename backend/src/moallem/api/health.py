"""Liveness and readiness endpoints (P1-03).

/healthz  liveness: process is up. Never touches dependencies.
/readyz   readiness: runs dependency checks; 503 if any fails.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from moallem import __version__
from moallem.health.checks import CheckResult, run_checks

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    checks = request.app.state.readiness_checks
    timeout: float = request.app.state.readiness_timeout
    results: list[CheckResult]
    try:
        # Hard ceiling so a hung check can never hang the probe.
        results = await asyncio.wait_for(run_checks(checks), timeout + 1.0)
    except TimeoutError:
        results = [CheckResult("readiness", False, "timeout")]
    body: dict[str, Any] = {
        "status": "ready" if all(r.ok for r in results) else "not_ready",
        "checks": {r.name: ("ok" if r.ok else r.detail) for r in results},
    }
    return JSONResponse(status_code=200 if body["status"] == "ready" else 503, content=body)
