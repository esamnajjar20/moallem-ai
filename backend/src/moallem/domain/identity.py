"""Bearer authentication core (ADR-017, PROPOSED). Stdlib only; no crypto dependency.

Pipeline: parse `Authorization: Bearer` -> TokenVerifier (signature; issuer/JWKS choice OPEN)
-> claim validation (iss, aud, exp, nbf, lifetime) -> (issuer, sub) -> global user id.
Every failure is the same AuthenticationRequired with the same message: no oracle for callers.
Unknown subjects are NOT auto-provisioned.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from moallem.domain.errors import AuthenticationRequired

_FAIL = "authentication required"


@dataclass(frozen=True, slots=True)
class Claims:
    issuer: str
    subject: str
    audience: tuple[str, ...]
    expires_at: float | None
    not_before: float | None = None
    issued_at: float | None = None


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Claims:
        """Verify the signature and return claims; raise AuthenticationRequired otherwise."""
        ...


class SubjectMapper(Protocol):
    def user_id_for(self, issuer: str, subject: str) -> str | None: ...


class InMemorySubjectMapper:
    """Test double. Real mapping: (issuer, sub) -> one global user (DB, P4)."""

    def __init__(self, items: Mapping[tuple[str, str], str] | None = None) -> None:
        self._items = dict(items or {})

    def user_id_for(self, issuer: str, subject: str) -> str | None:
        return self._items.get((issuer, subject))


_USER_NAMESPACE = uuid.UUID("6f1c5b0e-7d0b-5c1e-9a55-3f2f8f6f0a11")


class DerivedSubjectMapper:
    """Stable global user id = UUIDv5(issuer|sub). No table needed until P4 persistence.

    Creates no data and grants nothing: access still requires an ACTIVE membership.
    Trade-off: changing issuer changes ids (account linking would need a mapping table).
    """

    def user_id_for(self, issuer: str, subject: str) -> str | None:
        return str(uuid.uuid5(_USER_NAMESPACE, f"{issuer}|{subject}"))


def validate_claims(
    claims: Claims,
    *,
    issuer: str,
    audience: str,
    now: float,
    leeway_seconds: int,
    max_lifetime_seconds: int | None,
) -> None:
    if claims.issuer != issuer or audience not in claims.audience:
        raise AuthenticationRequired(_FAIL)
    if not claims.subject:
        raise AuthenticationRequired(_FAIL)
    if claims.expires_at is None or now > claims.expires_at + leeway_seconds:
        raise AuthenticationRequired(_FAIL)
    if claims.not_before is not None and now + leeway_seconds < claims.not_before:
        raise AuthenticationRequired(_FAIL)
    if max_lifetime_seconds is not None:
        if claims.issued_at is None or claims.expires_at - claims.issued_at > max_lifetime_seconds:
            raise AuthenticationRequired(_FAIL)


def _bearer_token(header: str | None) -> str:
    if header is None:
        raise AuthenticationRequired(_FAIL)
    parts = header.strip().split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise AuthenticationRequired(_FAIL)
    return parts[1]


def authenticate_bearer(
    header: str | None,
    *,
    verifier: TokenVerifier,
    mapper: SubjectMapper,
    issuer: str,
    audience: str,
    now: float,
    leeway_seconds: int,
    max_lifetime_seconds: int | None,
) -> str:
    claims = verifier.verify(_bearer_token(header))
    validate_claims(
        claims,
        issuer=issuer,
        audience=audience,
        now=now,
        leeway_seconds=leeway_seconds,
        max_lifetime_seconds=max_lifetime_seconds,
    )
    user_id = mapper.user_id_for(claims.issuer, claims.subject)
    if user_id is None:
        raise AuthenticationRequired(_FAIL)
    return user_id
