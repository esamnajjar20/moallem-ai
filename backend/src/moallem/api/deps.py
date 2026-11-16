"""Request-context dependencies. UNRUN: needs fastapi (sandbox had no network).

Authentication (ADR-017) is OPEN. `Authenticator` is the seam; the only implementation here is
DevAuthenticator, refused outside development/test. It trusts a header: never for production.
"""

from typing import Annotated, Protocol

from fastapi import Depends, Header, Request

from moallem.config import Environment
from moallem.domain.errors import DomainError
from moallem.domain.membership import ActiveContext, MembershipRepository, resolve_active_context
from moallem.errors import ErrorCode


class AuthenticationRequired(DomainError):
    code = ErrorCode.AUTHENTICATION_REQUIRED
    http_status = 401


class Authenticator(Protocol):
    def user_id(self, request: Request) -> str: ...


class NoAuthenticator:
    """Default until ADR-017 closes: every request is unauthenticated (fail closed)."""

    def user_id(self, request: Request) -> str:
        raise AuthenticationRequired("authentication required")


class DevAuthenticator:
    HEADER = "X-Dev-User-ID"

    def __init__(self, env: Environment) -> None:
        if env not in {Environment.DEVELOPMENT, Environment.TEST}:
            raise RuntimeError("DevAuthenticator is only allowed in development/test")

    def user_id(self, request: Request) -> str:
        uid = request.headers.get(self.HEADER, "").strip()
        if not uid:
            raise AuthenticationRequired("authentication required")
        return uid


def get_user_id(request: Request) -> str:
    auth: Authenticator = request.app.state.authenticator
    return auth.user_id(request)


def get_membership_repo(request: Request) -> MembershipRepository:
    repo: MembershipRepository = request.app.state.membership_repo
    return repo


def get_active_context(
    user_id: Annotated[str, Depends(get_user_id)],
    repo: Annotated[MembershipRepository, Depends(get_membership_repo)],
    x_active_membership_id: Annotated[str | None, Header()] = None,
) -> ActiveContext:
    return resolve_active_context(
        authenticated_user_id=user_id, header_value=x_active_membership_id, repo=repo
    )
