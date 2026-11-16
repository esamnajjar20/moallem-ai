import pytest

from moallem.domain.authorization import (
    DenyAllPolicy,
    StaticPolicy,
    authorize,
    require_tenant,
)
from moallem.domain.errors import PermissionDenied, ResourceNotFound
from moallem.domain.membership import ActiveContext

CTX_A = ActiveContext("u1", "m-a", "tenant-A", ("TEACHER",))
POLICY = StaticPolicy({"TEACHER": frozenset({"task.read"})})


def test_same_tenant_with_grant_is_allowed() -> None:
    authorize(CTX_A, "task.read", "tenant-A", POLICY)


def test_cross_tenant_is_not_found_even_when_action_would_be_granted() -> None:  # AT-015
    with pytest.raises(ResourceNotFound) as ei:
        authorize(CTX_A, "task.read", "tenant-B", POLICY)
    assert ei.value.http_status == 404


def test_cross_tenant_never_reveals_permission_outcome() -> None:
    # Granted vs not-granted action against a foreign tenant must look identical.
    with pytest.raises(ResourceNotFound) as granted:
        authorize(CTX_A, "task.read", "tenant-B", POLICY)
    with pytest.raises(ResourceNotFound) as ungranted:
        authorize(CTX_A, "task.delete", "tenant-B", POLICY)
    assert (granted.value.code, str(granted.value)) == (ungranted.value.code, str(ungranted.value))


def test_missing_resource_tenant_fails_closed() -> None:
    with pytest.raises(ResourceNotFound):
        require_tenant(CTX_A, None)


def test_same_tenant_without_grant_is_permission_denied() -> None:
    with pytest.raises(PermissionDenied) as ei:
        authorize(CTX_A, "task.delete", "tenant-A", POLICY)
    assert ei.value.http_status == 403


def test_default_policy_denies_everything() -> None:  # DEC-027 open => fail closed
    with pytest.raises(PermissionDenied):
        authorize(CTX_A, "task.read", "tenant-A", DenyAllPolicy())


def test_unknown_role_gets_nothing() -> None:
    ctx = ActiveContext("u1", "m-a", "tenant-A", ("STUDENT",))
    with pytest.raises(PermissionDenied):
        authorize(ctx, "task.read", "tenant-A", POLICY)
