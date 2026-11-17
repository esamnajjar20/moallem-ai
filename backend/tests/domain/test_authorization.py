import pytest

from moallem.domain.authorization import (
    ROLE_ADMIN,
    ROLE_TEACHER,
    PERM_MOODLE_COURSE_READ,
    PERM_QUIZ_APPROVE,
    PERM_QUIZ_GENERATE_REQUEST,
    PERM_TASK_READ,
    DenyAllPolicy,
    StaticPolicy,
    TeacherMVPPolicy,
    authorize,
    require_tenant,
)
from moallem.domain.errors import PermissionDenied, ResourceNotFound
from moallem.domain.membership import ActiveContext

CTX_TEACHER = ActiveContext("u1", "m-a", "tenant-A", (ROLE_TEACHER,))
CTX_ADMIN = ActiveContext("u2", "m-b", "tenant-A", (ROLE_ADMIN,))
CTX_STUDENT = ActiveContext("u3", "m-c", "tenant-A", ("STUDENT",))
POLICY = StaticPolicy({ROLE_TEACHER: frozenset({PERM_TASK_READ})})
MVP = TeacherMVPPolicy()


def test_same_tenant_with_grant_is_allowed() -> None:
    authorize(CTX_TEACHER, PERM_TASK_READ, "tenant-A", POLICY)


def test_cross_tenant_is_not_found_even_when_action_would_be_granted() -> None:  # AT-015
    with pytest.raises(ResourceNotFound) as ei:
        authorize(CTX_TEACHER, PERM_TASK_READ, "tenant-B", POLICY)
    assert ei.value.http_status == 404


def test_cross_tenant_never_reveals_permission_outcome() -> None:
    # Granted vs not-granted action against a foreign tenant must look identical.
    with pytest.raises(ResourceNotFound) as granted:
        authorize(CTX_TEACHER, PERM_TASK_READ, "tenant-B", POLICY)
    with pytest.raises(ResourceNotFound) as ungranted:
        authorize(CTX_TEACHER, "task.delete", "tenant-B", POLICY)
    assert (granted.value.code, str(granted.value)) == (ungranted.value.code, str(ungranted.value))


def test_missing_resource_tenant_fails_closed() -> None:
    with pytest.raises(ResourceNotFound):
        require_tenant(CTX_TEACHER, None)


def test_same_tenant_without_grant_is_permission_denied() -> None:
    with pytest.raises(PermissionDenied) as ei:
        authorize(CTX_TEACHER, "task.delete", "tenant-A", POLICY)
    assert ei.value.http_status == 403


def test_default_policy_denies_everything() -> None:
    with pytest.raises(PermissionDenied):
        authorize(CTX_TEACHER, PERM_TASK_READ, "tenant-A", DenyAllPolicy())


def test_unknown_role_gets_nothing() -> None:
    with pytest.raises(PermissionDenied):
        authorize(CTX_STUDENT, PERM_TASK_READ, "tenant-A", POLICY)


# ---------------------------------------------------------------------------
# TeacherMVPPolicy (DEC-027 APPROVED)
# ---------------------------------------------------------------------------


def test_teacher_mvp_grants_core_actions() -> None:
    for action in (
        PERM_MOODLE_COURSE_READ,
        PERM_QUIZ_GENERATE_REQUEST,
        PERM_QUIZ_APPROVE,
        PERM_TASK_READ,
    ):
        authorize(CTX_TEACHER, action, "tenant-A", MVP)


def test_admin_receives_same_mvp_grants() -> None:
    authorize(CTX_ADMIN, PERM_QUIZ_APPROVE, "tenant-A", MVP)
    authorize(CTX_ADMIN, PERM_MOODLE_COURSE_READ, "tenant-A", MVP)


def test_teacher_mvp_denies_unknown_action() -> None:
    with pytest.raises(PermissionDenied):
        authorize(CTX_TEACHER, "admin.everything", "tenant-A", MVP)


def test_student_role_denied_by_mvp_policy() -> None:
    with pytest.raises(PermissionDenied):
        authorize(CTX_STUDENT, PERM_TASK_READ, "tenant-A", MVP)


def test_teacher_mvp_still_enforces_tenant_isolation() -> None:
    with pytest.raises(ResourceNotFound):
        authorize(CTX_TEACHER, PERM_TASK_READ, "tenant-B", MVP)
