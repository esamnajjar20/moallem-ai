"""Tenant isolation + permission decision seam (P2-01 / P2-03; DEC-027, DEC-032).

Two independent checks, always in this order:

1. Tenant: a resource owned by another tenant is reported as NOT FOUND (disclosure policy,
   AT-015): the caller learns nothing about whether it exists. This holds regardless of any
   later DB-level isolation (RLS etc., DEC-032 still OPEN): it is the application-layer guard.
2. Permission: allowed only if the policy explicitly grants (role, action). The matrix itself is
   DEC-027 (OPEN), so the only policy shipped here denies everything: fail closed.
"""

from collections.abc import Mapping
from typing import Protocol

from moallem.domain.errors import PermissionDenied, ResourceNotFound
from moallem.domain.membership import ActiveContext


class PermissionPolicy(Protocol):
    def allows(self, roles: tuple[str, ...], action: str) -> bool: ...


class DenyAllPolicy:
    """Default until DEC-027 closes: nothing is permitted."""

    def allows(self, roles: tuple[str, ...], action: str) -> bool:
        return False


class StaticPolicy:
    """Explicit allow-list {role: {actions}}. For tests / once DEC-027 provides the matrix."""

    def __init__(self, grants: Mapping[str, frozenset[str]]) -> None:
        self._grants = dict(grants)

    def allows(self, roles: tuple[str, ...], action: str) -> bool:
        return any(action in self._grants.get(r, frozenset()) for r in roles)


def require_tenant(ctx: ActiveContext, resource_tenant_id: str | None) -> None:
    """Raise ResourceNotFound unless the resource belongs to the active tenant."""
    if resource_tenant_id is None or resource_tenant_id != ctx.tenant_id:
        raise ResourceNotFound("resource not found")


def authorize(
    ctx: ActiveContext, action: str, resource_tenant_id: str | None, policy: PermissionPolicy
) -> None:
    require_tenant(ctx, resource_tenant_id)  # first: never leak existence across tenants
    if not policy.allows(ctx.roles, action):
        raise PermissionDenied("permission denied")
