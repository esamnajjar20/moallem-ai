"""FastAPI application factory.

Run: uvicorn --factory moallem.api.app:create_app
Invalid configuration aborts startup (fail fast) before the server accepts traffic.
"""

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from moallem import __version__
from moallem.api.deps import (
    Authenticator,
    BearerAuthenticator,
    DevAuthenticator,
    NoAuthenticator,
)
from moallem.api.health import router as health_router
from moallem.api.jwks import UrlJwks, jwks_url_for_issuer
from moallem.api.me import router as me_router
from moallem.api.schemas import ErrorDetails, ErrorEnvelope, FieldError
from moallem.config import Environment, Settings, load_settings
from moallem.domain.errors import DomainError
from moallem.domain.identity import DerivedSubjectMapper
from moallem.domain.membership import InMemoryMembershipRepository, MembershipRepository
from moallem.domain.rs256 import Rs256Verifier
from moallem.errors import ErrorCode
from moallem.health.checks import Check, tcp_check
from moallem.logging import configure_logging, request_id_var

log = logging.getLogger("moallem.api")

_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
REQUEST_ID_HEADER = "X-Request-ID"


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def _request_id_of(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else _new_request_id()


def _error_response(
    request: Request,
    status: int,
    code: ErrorCode,
    message: str,
    *,
    retryable: bool = False,
    details: ErrorDetails | None = None,
) -> JSONResponse:
    rid = _request_id_of(request)
    envelope = ErrorEnvelope(
        code=code, message=message, details=details, request_id=rid, retryable=retryable
    )
    return JSONResponse(
        status_code=status,
        content=envelope.model_dump(mode="json", exclude_none=True),
        headers={REQUEST_ID_HEADER: rid},
    )


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    # Field names and error types only: never echo submitted values.
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    field_errors = [
        FieldError(field=".".join(str(p) for p in e["loc"]), code=str(e["type"])) for e in errors
    ]
    return _error_response(
        request,
        400,
        ErrorCode.VALIDATION_FAILED,
        "Request validation failed.",
        details=ErrorDetails(field_errors=field_errors),
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    status = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    if status == 404:
        return _error_response(request, 404, ErrorCode.RESOURCE_NOT_FOUND, "Resource not found.")
    if status >= 500:
        return _error_response(request, status, ErrorCode.INTERNAL_ERROR, "Internal error.")
    return _error_response(request, status, ErrorCode.VALIDATION_FAILED, "Request not allowed.")


async def _domain_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, DomainError):
        return _error_response(request, exc.http_status, exc.code, str(exc))
    return _error_response(request, 500, ErrorCode.INTERNAL_ERROR, "Internal error.")


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", exc_info=exc, extra={"path": request.url.path})
    return _error_response(request, 500, ErrorCode.INTERNAL_ERROR, "Internal error.")


def create_app(
    settings: Settings | None = None,
    checks: Sequence[Check] | None = None,
    authenticator: Authenticator | None = None,
    membership_repo: MembershipRepository | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level.value, service="moallem-api", env=settings.env.value)

    if checks is None:
        built: list[Check] = []
        if settings.database_url is not None:
            built.append(
                tcp_check(
                    "postgres",
                    settings.database_url.get_secret_value(),
                    settings.readiness_timeout_seconds,
                )
            )
        if settings.redis_url is not None:
            built.append(
                tcp_check(
                    "redis",
                    settings.redis_url.get_secret_value(),
                    settings.readiness_timeout_seconds,
                )
            )
        checks = built

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("api.started", extra={"config": settings.safe_summary(), "version": __version__})
        yield
        log.info("api.stopped")

    prod = settings.env is Environment.PRODUCTION
    app = FastAPI(
        title="Moallem AI API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if prod else "/docs",
        redoc_url=None,
        openapi_url=None if prod else "/openapi.json",
    )
    app.state.settings = settings
    if authenticator is None:
        dev = settings.env in {Environment.DEVELOPMENT, Environment.TEST}
        if settings.auth_issuer is not None:
            # Validated all-or-none by Settings. Auth0 JWKS: ttl 1h, refresh gap 60s, 5s timeout.
            assert settings.auth_audience is not None  # noqa: S101
            assert settings.auth_max_token_lifetime_seconds is not None  # noqa: S101
            authenticator = BearerAuthenticator(
                Rs256Verifier(
                    UrlJwks(
                        jwks_url_for_issuer(settings.auth_issuer),
                        ttl_seconds=3600,
                        min_refresh_interval_seconds=60,
                        timeout_seconds=5,
                    )
                ),
                DerivedSubjectMapper(),
                issuer=settings.auth_issuer,
                audience=settings.auth_audience,
                leeway_seconds=30,
                max_lifetime_seconds=settings.auth_max_token_lifetime_seconds,
            )
        else:
            authenticator = DevAuthenticator(settings.env) if dev else NoAuthenticator()
    app.state.authenticator = authenticator
    # Placeholder until P4 persistence; an empty repo means nobody has a membership (fail closed).
    app.state.membership_repo = membership_repo or InMemoryMembershipRepository()
    app.state.readiness_checks = list(checks)
    app.state.readiness_timeout = settings.readiness_timeout_seconds

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        rid = incoming if _REQUEST_ID_OK.fullmatch(incoming) else _new_request_id()
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        return response

    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(DomainError, _domain_handler)
    app.add_exception_handler(Exception, _unhandled_handler)

    # Operational endpoints live at the root, outside /api/v1: they are not part of the
    # 17-operation product contract (see docs/PHASE1_STATUS.md, "Contract notes").
    app.include_router(health_router)
    app.include_router(me_router)
    return app
