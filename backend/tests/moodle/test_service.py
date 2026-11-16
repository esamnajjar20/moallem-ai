import pytest

from moallem.domain.authorization import DenyAllPolicy, StaticPolicy
from moallem.domain.errors import PermissionDenied, ResourceNotFound
from moallem.domain.membership import ActiveContext
from moallem.domain.secrets import InMemoryVault
from moallem.moodle.errors import ConnectionNotActive
from moallem.moodle.service import (
    PERM_CONNECTION_READ,
    PERM_COURSE_CONTENT_READ,
    PERM_COURSE_READ,
    ConnectionStatus,
    MoodleConnection,
    MoodleReadService,
    new_connection_repository,
)
from tests.moodle.fakes import PUBLIC, SITE_INFO, TOKEN, FakeResolver, FakeTransport

A = ActiveContext("u1", "m-a", "tenant-A", ("TEACHER",))
B = ActiveContext("u2", "m-b", "tenant-B", ("TEACHER",))
ALLOW = StaticPolicy(
    {"TEACHER": frozenset({PERM_CONNECTION_READ, PERM_COURSE_READ, PERM_COURSE_CONTENT_READ})}
)


def _svc(policy=ALLOW, status=ConnectionStatus.ACTIVE, user_id=42):  # type: ignore[no-untyped-def]
    vault, repo, t = InMemoryVault(), new_connection_repository(), FakeTransport()
    ref = vault.put(A, TOKEN)
    conn = MoodleConnection("c1", "tenant-A", "https://moodle.example.edu", ref, status, user_id)
    repo.add(A, conn)
    t.json_for("core_webservice_get_site_info", SITE_INFO)
    t.json_for("core_enrol_get_users_courses", [{"id": 1, "fullname": "Algebra"}])
    t.json_for("core_course_get_contents", [])
    svc = MoodleReadService(
        connections=repo, vault=vault, policy=policy, transport=t, resolver=FakeResolver(PUBLIC)
    )
    return svc, t


def test_happy_path_reads_through_tenant_context() -> None:
    svc, t = _svc()
    assert svc.discover_capabilities(A, "c1").read_supported
    assert [c.course_id for c in svc.list_courses(A, "c1").items] == ["1"]
    assert svc.course_contents(A, "c1", "1").sections == ()
    assert all(call["form"]["wstoken"] == TOKEN for call in t.calls)


def test_foreign_tenant_gets_not_found_and_no_moodle_call() -> None:  # AT-015
    svc, t = _svc()
    for fn in (
        lambda: svc.discover_capabilities(B, "c1"),
        lambda: svc.list_courses(B, "c1"),
        lambda: svc.course_contents(B, "c1", "1"),
        lambda: svc.list_courses(A, "does-not-exist"),
    ):
        with pytest.raises(ResourceNotFound):
            fn()
    assert t.calls == []


def test_default_deny_policy_blocks_everything_before_moodle() -> None:
    svc, t = _svc(policy=DenyAllPolicy())
    with pytest.raises(PermissionDenied):
        svc.list_courses(A, "c1")
    assert t.calls == []


def test_permission_is_per_action() -> None:
    only_courses = StaticPolicy({"TEACHER": frozenset({PERM_COURSE_READ})})
    svc, _ = _svc(policy=only_courses)
    svc.list_courses(A, "c1")
    with pytest.raises(PermissionDenied):
        svc.course_contents(A, "c1", "1")
    with pytest.raises(PermissionDenied):
        svc.discover_capabilities(A, "c1")


@pytest.mark.parametrize(
    "status", [ConnectionStatus.DISCONNECTED, ConnectionStatus.CREDENTIAL_INVALID]
)
def test_inactive_connection_blocked_before_secret_reveal(status: ConnectionStatus) -> None:
    svc, t = _svc(status=status)
    with pytest.raises(ConnectionNotActive):
        svc.list_courses(A, "c1")
    assert t.calls == []


def test_courses_need_a_validated_moodle_user() -> None:
    svc, _ = _svc(user_id=None)
    with pytest.raises(ConnectionNotActive):
        svc.list_courses(A, "c1")
