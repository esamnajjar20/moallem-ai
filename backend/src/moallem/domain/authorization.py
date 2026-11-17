"""Tenant isolation + permission decision seam (P2-01 / P2-03; DEC-027, DEC-032).

Two independent checks, always in this order:

1. Tenant: a resource owned by another tenant is reported as NOT FOUND (disclosure policy,
   AT-015): the caller learns nothing about whether it exists. This holds regardless of any
   later DB-level isolation (RLS etc., DEC-032 still OPEN): it is the application-layer guard.
2. Permission: allowed only if the policy explicitly grants (role, action).

DEC-027 is APPROVED for the Teacher MVP matrix (2026-11-17).
The production composition default remains DenyAllPolicy until the approved policy is
explicitly injected (or enabled by configuration). This keeps fail-closed behaviour.
"""

from collections.abc import Mapping
from typing import Protocol

from moallem.domain.errors import PermissionDenied, ResourceNotFound
from moallem.domain.membership import ActiveContext

# ---------------------------------------------------------------------------
# Permission keys (stable contract — keep in sync with DEC-027 document)
# ---------------------------------------------------------------------------

PERM_MOODLE_CONNECTION_READ = "moodle.connection.read"
PERM_MOODLE_CONNECTION_MANAGE = "moodle.connection.manage"
PERM_MOODLE_COURSE_READ = "moodle.course.read"
PERM_MOODLE_COURSE_CONTENT_READ = "moodle.course.content.read"
PERM_QUIZ_GENERATE_REQUEST = "quiz.generate.request"
PERM_QUIZ_DRAFT_READ = "quiz.draft.read"
PERM_QUIZ_QUALITY_VIEW = "quiz.quality.view"
PERM_QUIZ_APPROVE = "quiz.approve"
PERM_QUIZ_REJECT = "quiz.reject"
PERM_QUIZ_PUBLISH = "quiz.publish"
PERM_TASK_CREATE = "task.create"
PERM_TASK_READ = "task.read"
PERM_TASK_EVENTS_READ = "task.events.read"
PERM_AI_USAGE_READ = "ai.usage.read"

# All permissions granted to TEACHER (and ADMIN) in the approved MVP matrix.
_TEACHER_MVP_ACTIONS: frozenset[str] = frozenset(
    {
        PERM_MOODLE_CONNECTION_READ,
        PERM_MOODLE_CONNECTION_MANAGE,
        PERM_MOODLE_COURSE_READ,
        PERM_MOODLE_COURSE_CONTENT_READ,
        PERM_QUIZ_GENERATE_REQUEST,
        PERM_QUIZ_DRAFT_READ,
        PERM_QUIZ_QUALITY_VIEW,
        PERM_QUIZ_APPROVE,
        PERM_QUIZ_REJECT,
        PERM_QUIZ_PUBLISH,
        PERM_TASK_CREATE,
        PERM_TASK_READ,
        PERM_TASK_EVENTS_READ,
        PERM_AI_USAGE_READ,
    }
)

# Role names used in ActiveContext.roles
ROLE_TEACHER = "TEACHER"
ROLE_ADMIN = "ADMIN"


class PermissionPolicy(Protocol):
    def allows(self, roles: tuple[str, ...], action: str) -> bool: ...


class DenyAllPolicy:
    """Safe production default: nothing is permitted until an approved policy is injected."""

    def allows(self, roles: tuple[str, ...], action: str) -> bool:
        return False


class StaticPolicy:
    """Explicit allow-list {role: {actions}}. Used by tests and by TeacherMVPPolicy."""

    def __init__(self, grants: Mapping[str, frozenset[str]]) -> None:
        self._grants = dict(grants)

    def allows(self, roles: tuple[str, ...], action: str) -> bool:
        return any(action in self._grants.get(r, frozenset()) for r in roles)


class TeacherMVPPolicy(StaticPolicy):
    """Approved DEC-027 matrix for the Teacher MVP Vertical Slice.

    Grants the fixed set of actions to TEACHER and ADMIN roles.
    Any other role receives nothing. Any unlisted action is denied.
    """

    def __init__(self) -> None:
        super().__init__(
            {
                ROLE_TEACHER: _TEACHER_MVP_ACTIONS,
                ROLE_ADMIN: _TEACHER_MVP_ACTIONS,
            }
        )


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
