"""Resolve the acting membership for a worker task from durable state (never hard-coded)."""

from __future__ import annotations

from moallem.domain.errors import MembershipContextInvalid
from moallem.domain.membership import (
    ActiveContext,
    MembershipRepository,
    MembershipStatus,
)


class ActorContextResolver:
    """Rebuild the ActiveContext of the task's actor at execution time.

    Roles and status are re-read on every call, so a membership that was suspended or
    revoked after approval can no longer publish.
    """

    def __init__(self, memberships: MembershipRepository) -> None:
        self._memberships = memberships

    def resolve(self, tenant_id: str, membership_id: str) -> ActiveContext:
        membership = self._memberships.get(membership_id)
        if (
            membership is None
            or membership.tenant_id != tenant_id
            or membership.status is not MembershipStatus.ACTIVE
        ):
            raise MembershipContextInvalid("invalid membership context")
        return ActiveContext(
            user_id=membership.user_id,
            membership_id=membership.membership_id,
            tenant_id=membership.tenant_id,
            roles=membership.roles,
        )
