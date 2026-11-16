import uuid

import pytest

from moallem.domain.errors import (
    MembershipContextInvalid,
    MembershipContextMalformed,
    MembershipContextRequired,
)
from moallem.domain.membership import (
    InMemoryMembershipRepository,
    Membership,
    MembershipStatus,
    resolve_active_context,
)

U1, U2 = "user-1", "user-2"
M_A, M_B, M_SUSP, M_REV, M_FOREIGN = (str(uuid.uuid4()) for _ in range(5))


def _repo() -> InMemoryMembershipRepository:
    def m(mid: str, user: str, tenant: str, st: MembershipStatus) -> Membership:
        return Membership(mid, user, tenant, ("TEACHER",), st)

    return InMemoryMembershipRepository(
        {
            M_A: m(M_A, U1, "tenant-A", MembershipStatus.ACTIVE),
            M_B: m(M_B, U1, "tenant-B", MembershipStatus.ACTIVE),
            M_SUSP: m(M_SUSP, U1, "tenant-A", MembershipStatus.SUSPENDED),
            M_REV: m(M_REV, U1, "tenant-A", MembershipStatus.REVOKED),
            M_FOREIGN: m(M_FOREIGN, U2, "tenant-C", MembershipStatus.ACTIVE),
        }
    )


def _resolve(header: str | None, user: str = U1):  # type: ignore[no-untyped-def]
    return resolve_active_context(authenticated_user_id=user, header_value=header, repo=_repo())


def test_missing_or_blank_header_is_required_error() -> None:
    for h in (None, "", "   "):
        with pytest.raises(MembershipContextRequired):
            _resolve(h)


def test_malformed_unknown_foreign_suspended_revoked_are_indistinguishable() -> None:
    errors = []
    for h in (str(uuid.uuid4()), M_FOREIGN, M_SUSP, M_REV):
        with pytest.raises(MembershipContextInvalid) as ei:
            _resolve(h)
        errors.append((ei.value.code, str(ei.value), ei.value.http_status))
    assert len(set(errors)) == 1  # no membership enumeration
    assert errors[0][2] == 403  # DEC-039: invalid context is 403, missing header is 400


def test_missing_header_is_400() -> None:
    with pytest.raises(MembershipContextRequired) as ei:
        _resolve(None)
    assert ei.value.http_status == 400


def test_malformed_header_is_a_400_format_error_not_403() -> None:
    with pytest.raises(MembershipContextMalformed) as ei:
        _resolve("not-a-uuid")
    assert (ei.value.http_status, ei.value.code.value) == (400, "VALIDATION_FAILED")


def test_valid_context_derives_tenant_and_roles_server_side() -> None:  # AT-031/AT-037
    a, b = _resolve(M_A), _resolve(M_B)
    assert (a.tenant_id, b.tenant_id) == ("tenant-A", "tenant-B")
    assert a.roles == ("TEACHER",) and a.user_id == U1


def test_uppercase_and_padded_uuid_accepted_once_canonicalized() -> None:
    assert _resolve(f"  {M_A.upper()} ").membership_id == M_A


def test_other_users_valid_membership_is_rejected() -> None:
    with pytest.raises(MembershipContextInvalid):
        _resolve(M_A, user=U2)
