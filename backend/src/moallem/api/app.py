"""FastAPI application factory.

Run: uvicorn --factory moallem.api.app:create_app
Invalid configuration aborts startup (fail fast) before the server accepts traffic.
"""

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
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
from moallem.api.tasks import router as task_router
from moallem.config import Environment, Settings, load_settings
from moallem.domain.authorization import DenyAllPolicy, PermissionPolicy
from moallem.domain.errors import AuthenticationRequired, DomainError
from moallem.domain.identity import DerivedSubjectMapper
from moallem.domain.membership import InMemoryMembershipRepository, MembershipRepository
from moallem.domain.rs256 import Rs256Verifier
from moallem.errors import ErrorCode
from moallem.health.checks import Check, CheckResult, tcp_check
from moallem.logging import configure_logging, request_id_var
from moallem.moodle.routes import router as moodle_router
from moallem.moodle.service import MoodleReadService
from moallem.persistence.database import SessionFactory, check_database, create_database
from moallem.persistence.repositories import (
    PostgresMembershipRepository,
    PostgresSubjectMapper,
    new_postgres_connection_repository,
)
from moallem.persistence.task_repository import PostgresTaskRepository
from moallem.persistence.publishing_repository import PostgresPublicationRepository

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
        response = _error_response(request, exc.http_status, exc.code, str(exc))
        if isinstance(exc, AuthenticationRequired):
            response.headers["WWW-Authenticate"] = 'Bearer realm="moallem-api"'
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response
    return _error_response(request, 500, ErrorCode.INTERNAL_ERROR, "Internal error.")


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", exc_info=exc, extra={"path": request.url.path})
    return _error_response(request, 500, ErrorCode.INTERNAL_ERROR, "Internal error.")


def create_app(
    settings: Settings | None = None,
    checks: Sequence[Check] | None = None,
    authenticator: Authenticator | None = None,
    membership_repo: MembershipRepository | None = None,
    moodle_read_service: MoodleReadService | None = None,
    permission_policy: PermissionPolicy | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    if settings.env is not Environment.TEST and (
        authenticator is not None or membership_repo is not None
    ):
        raise RuntimeError("authentication and membership adapters may only be injected in tests")
    configure_logging(settings.log_level.value, service="moallem-api", env=settings.env.value)

    db_engine = None
    db_sessions: SessionFactory | None = None
    if settings.database_url is not None:
        db_engine, db_sessions = create_database(
            settings.database_url.get_secret_value(),
            connect_timeout_seconds=max(1, int(settings.readiness_timeout_seconds)),
        )

    auth_jwks: UrlJwks | None = None
    if authenticator is None and settings.auth_issuer is not None:
        auth_jwks = UrlJwks(
            jwks_url_for_issuer(settings.auth_issuer),
            ttl_seconds=3600,
            min_refresh_interval_seconds=60,
            timeout_seconds=5,
        )
        if db_sessions is None and settings.env is not Environment.TEST:
            raise RuntimeError("Auth0 authentication requires PostgreSQL identity mapping")

    built: list[Check] = []
    if db_engine is not None:

        async def _postgres_check() -> CheckResult:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(check_database, db_engine),
                    timeout=settings.readiness_timeout_seconds,
                )
            except (SQLAlchemyError, OSError, TimeoutError):
                return CheckResult("postgres", False, "query_failed")
            if settings.auth_issuer is not None:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(_check_auth_schema, db_engine),
                        timeout=settings.readiness_timeout_seconds,
                    )
                except (SQLAlchemyError, OSError, TimeoutError):
                    return CheckResult("postgres", False, "auth_schema_not_migrated")
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(_check_publishing_schema, db_engine),
                    timeout=settings.readiness_timeout_seconds,
                )
            except (SQLAlchemyError, OSError, TimeoutError):
                return CheckResult("postgres", False, "publishing_schema_not_migrated")
            return CheckResult("postgres", True, "query_ok")

        built.append(_postgres_check)
    if settings.redis_url is not None:
        built.append(
            tcp_check(
                "redis",
                settings.redis_url.get_secret_value(),
                settings.readiness_timeout_seconds,
            )
        )
    if auth_jwks is not None:
        jwks_client = auth_jwks

        async def _auth0_jwks_check() -> CheckResult:
            try:
                ok = await asyncio.wait_for(
                    asyncio.to_thread(jwks_client.has_signing_keys),
                    timeout=settings.readiness_timeout_seconds + 1.0,
                )
            except (OSError, ValueError, TimeoutError):
                ok = False
            return CheckResult("auth0_jwks", ok, "keys_loaded" if ok else "issuer_unavailable")

        built.append(_auth0_jwks_check)
    if checks is None:
        checks = built
    elif settings.env is not Environment.TEST:
        # Custom health checks may extend runtime readiness, never replace mandatory
        # PostgreSQL/Auth0 checks that enforce the authentication deployment contract.
        checks = [*built, *checks]

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("api.started", extra={"config": settings.safe_summary(), "version": __version__})
        try:
            yield
        finally:
            if db_engine is not None:
                db_engine.dispose()
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
            # Auth0 access-token verification only. Login/refresh/logout are handled by the
            # native OIDC client; the API never receives a password or refresh token.
            assert settings.auth_audience is not None  # noqa: S101
            assert settings.auth_max_token_lifetime_seconds is not None  # noqa: S101
            if auth_jwks is None:
                raise RuntimeError("Auth0 JWKS verifier was not initialized")
            authenticator = BearerAuthenticator(
                Rs256Verifier(auth_jwks),
                PostgresSubjectMapper(db_sessions)
                if db_sessions is not None
                else DerivedSubjectMapper(),
                issuer=settings.auth_issuer,
                audience=settings.auth_audience,
                leeway_seconds=30,
                max_lifetime_seconds=settings.auth_max_token_lifetime_seconds,
            )
        else:
            authenticator = DevAuthenticator(settings.env) if dev else NoAuthenticator()
    app.state.authenticator = authenticator
    app.state.db_engine = db_engine
    app.state.db_sessions = db_sessions
    app.state.membership_repo = membership_repo or (
        PostgresMembershipRepository(db_sessions)
        if db_sessions is not None
        else InMemoryMembershipRepository()
    )
    app.state.moodle_connection_repository = (
        new_postgres_connection_repository(db_sessions) if db_sessions is not None else None
    )
    app.state.moodle_read_service = moodle_read_service
    app.state.permission_policy = permission_policy or DenyAllPolicy()
    app.state.task_repository = (
        PostgresTaskRepository(db_sessions) if db_sessions is not None else None
    )
    app.state.publication_repository = (
        PostgresPublicationRepository(db_sessions) if db_sessions is not None else None
    )
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
    # The OpenAPI server URL already includes /api/v1. Register the product routes there
    # and keep unversioned aliases temporarily for older clients; aliases are hidden from
    # generated OpenAPI so there is one canonical contract surface.
    app.include_router(moodle_router, prefix="/api/v1")
    app.include_router(task_router, prefix="/api/v1")
    app.include_router(moodle_router, include_in_schema=False)
    app.include_router(task_router, include_in_schema=False)
    return app


def _check_auth_schema(engine: Engine) -> None:
    """Require the account lifecycle migration before the Auth0 resource server is ready."""
    with engine.connect() as connection:
        connection.execute(text("SELECT auth_status FROM users LIMIT 0"))


def _check_publishing_schema(engine: Engine) -> None:
    """Require the P7 durable approval/publish ledger before the API is ready."""
    statements = (
        "SELECT result_payload FROM tasks LIMIT 0",
        "SELECT id, snapshot_hash FROM quiz_draft_snapshots LIMIT 0",
        "SELECT id, idempotency_key_hash FROM quiz_approvals LIMIT 0",
        "SELECT id, external_operation_key FROM publish_intents LIMIT 0",
        "SELECT id, external_step_key FROM tool_invocations LIMIT 0",
    )
    with engine.connect() as connection:
        for statement in statements:
            connection.execute(text(statement))
