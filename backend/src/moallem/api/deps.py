"""Request-context dependencies. UNRUN: needs fastapi (sandbox had no network).

Authentication (ADR-017) is OPEN. `Authenticator` is the seam; the only implementation here is
DevAuthenticator, refused outside development/test. It trusts a header: never for production.
"""

import time
from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import Depends, Header, Request

from moallem.config import Environment
from moallem.domain.errors import AuthenticationRequired
from moallem.domain.identity import SubjectMapper, TokenVerifier, authenticate_bearer
from moallem.domain.membership import ActiveContext, MembershipRepository, resolve_active_context


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


class BearerAuthenticator:
    """ADR-017 seam (PROPOSED): Bearer token -> verified claims -> mapped global user.

    Signature verification lives in the injected TokenVerifier (issuer/JWKS choice is OPEN).
    Not wired into create_app until issuer/audience settings are approved.
    """

    def __init__(
        self,
        verifier: TokenVerifier,
        mapper: SubjectMapper,
        *,
        issuer: str,
        audience: str,
        leeway_seconds: int,
        max_lifetime_seconds: int | None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._verifier = verifier
        self._mapper = mapper
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway_seconds
        self._max_lifetime = max_lifetime_seconds
        self._clock = clock

    def user_id(self, request: Request) -> str:
        return authenticate_bearer(
            request.headers.get("Authorization"),
            verifier=self._verifier,
            mapper=self._mapper,
            issuer=self._issuer,
            audience=self._audience,
            now=self._clock(),
            leeway_seconds=self._leeway,
            max_lifetime_seconds=self._max_lifetime,
        )


def get_user_id(request: Request) -> str:
    auth: Authenticator = request.app.state.authenticator
    return auth.user_id(request)


def get_membership_repo(request: Request) -> MembershipRepository:
    repo: MembershipRepository = request.app.state.membership_repo
    return repo


def get_active_context(
    user_id: Annotated[str, Depends(get_user_id)],
    repo: Annotated[MembershipRepository, Depends(get_membership_repo)],
    x_active_membership_id: Annotated[str | None, Header(alias="X-Active-Membership-ID")] = None,
) -> ActiveContext:
    return resolve_active_context(
        authenticated_user_id=user_id, header_value=x_active_membership_id, repo=repo
    )
