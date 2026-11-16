"""Active membership context (DEC-039 / GAP-API-005 / AT-037).

The client sends ONLY X-Active-Membership-ID. user, tenant and roles are derived server-side from
the repository; tenant_id/role sent by the client are never read. Authentication itself (ADR-017)
is OUT of scope here: `authenticated_user_id` must come from a verified session by the caller.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from moallem.domain.errors import MembershipContextInvalid, MembershipContextRequired


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class Membership:
    membership_id: str
    user_id: str
    tenant_id: str
    roles: tuple[str, ...]
    status: MembershipStatus


@dataclass(frozen=True, slots=True)
class ActiveContext:
    user_id: str
    membership_id: str
    tenant_id: str
    roles: tuple[str, ...]


class MembershipRepository(Protocol):
    def get(self, membership_id: str) -> Membership | None: ...

    def list_for_user(self, user_id: str) -> list[Membership]: ...


class InMemoryMembershipRepository:
    """Test double only."""

    def __init__(self, items: Mapping[str, Membership] | None = None) -> None:
        self._items = dict(items or {})

    def get(self, membership_id: str) -> Membership | None:
        return self._items.get(membership_id)

    def list_for_user(self, user_id: str) -> list[Membership]:
        return [m for m in self._items.values() if m.user_id == user_id]


def resolve_active_context(
    *, authenticated_user_id: str, header_value: str | None, repo: MembershipRepository
) -> ActiveContext:
    """Re-run on EVERY tenant-scoped request (never cache across requests)."""
    if header_value is None or not header_value.strip():
        raise MembershipContextRequired("X-Active-Membership-ID is required")
    try:
        canonical = str(uuid.UUID(header_value.strip()))
    except ValueError as exc:
        raise MembershipContextInvalid("invalid membership context") from exc
    m = repo.get(canonical)
    # Unknown, someone else's, suspended and revoked all look identical to the caller:
    # no membership enumeration.
    if m is None or m.user_id != authenticated_user_id or m.status is not MembershipStatus.ACTIVE:
        raise MembershipContextInvalid("invalid membership context")
    return ActiveContext(m.user_id, m.membership_id, m.tenant_id, m.roles)
