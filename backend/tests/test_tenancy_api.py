"""HTTP-level AT-037 / AT-031 / AT-015 over a probe route. Needs fastapi + httpx (CI)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from moallem.api.app import create_app
from moallem.api.deps import get_active_context
from moallem.config import Settings
from moallem.domain.authorization import StaticPolicy, authorize
from moallem.domain.membership import (
    ActiveContext,
    InMemoryMembershipRepository,
    Membership,
    MembershipStatus,
)

M_A, M_B, M_SUSP, M_FOREIGN = (str(uuid.uuid4()) for _ in range(4))
T_A, T_B, T_C = (str(uuid.uuid4()) for _ in range(3))
DOCS = {"doc-a": T_A, "doc-b": T_B}  # resource -> owning tenant
POLICY = StaticPolicy({"TEACHER": frozenset({"doc.read"})})


def _client() -> TestClient:
    def m(mid: str, user: str, tenant: str, st: MembershipStatus) -> Membership:
        return Membership(mid, user, tenant, ("TEACHER",), st)

    repo = InMemoryMembershipRepository(
        {
            M_A: m(M_A, "u1", T_A, MembershipStatus.ACTIVE),
            M_B: m(M_B, "u1", T_B, MembershipStatus.ACTIVE),
            M_SUSP: m(M_SUSP, "u1", T_A, MembershipStatus.SUSPENDED),
            M_FOREIGN: m(M_FOREIGN, "u2", T_C, MembershipStatus.ACTIVE),
        }
    )
    app = create_app(Settings(env="test", _env_file=None), checks=[], membership_repo=repo)
    probe = APIRouter()

    @probe.get("/_probe/ctx")
    async def ctx_probe(
        ctx: Annotated[ActiveContext, Depends(get_active_context)],
    ) -> dict[str, str]:
        return {"tenant_id": ctx.tenant_id, "membership_id": ctx.membership_id}

    @probe.get("/_probe/docs/{doc_id}")
    async def doc(
        doc_id: str, ctx: Annotated[ActiveContext, Depends(get_active_context)]
    ) -> dict[str, str]:
        authorize(ctx, "doc.read", DOCS.get(doc_id), POLICY)
        return {"doc_id": doc_id}

    app.include_router(probe)
    return TestClient(app)


def _h(mid: str | None, user: str = "u1") -> dict[str, str]:
    h = {"X-Dev-User-ID": user}
    if mid is not None:
        h["X-Active-Membership-ID"] = mid
    return h


def test_unauthenticated_is_401() -> None:
    r = _client().get("/_probe/ctx", headers={"X-Active-Membership-ID": M_A})
    assert r.status_code == 401 and r.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_missing_and_malformed_header_are_400() -> None:
    c = _client()
    r = c.get("/_probe/ctx", headers=_h(None))
    assert r.status_code == 400 and r.json()["code"] == "MEMBERSHIP_CONTEXT_REQUIRED"
    r = c.get("/_probe/ctx", headers=_h("not-a-uuid"))
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_FAILED"


def test_foreign_unknown_and_suspended_are_identical_403() -> None:
    c = _client()
    bodies = []
    for mid in (M_FOREIGN, str(uuid.uuid4()), M_SUSP):
        r = c.get("/_probe/ctx", headers=_h(mid))
        assert r.status_code == 403
        j = r.json()
        bodies.append((j["code"], j["message"]))
    assert len(set(bodies)) == 1


def test_valid_context_derives_tenant_server_side_and_ignores_client_tenant() -> None:
    c = _client()
    r = c.get(
        f"/_probe/ctx?tenant_id={T_B}",
        headers={**_h(M_A), "X-Tenant-ID": T_B, "X-Role": "ADMIN"},
    )
    assert r.status_code == 200 and r.json()["tenant_id"] == T_A


def test_switching_membership_switches_tenant() -> None:  # AT-031
    c = _client()
    assert c.get("/_probe/ctx", headers=_h(M_A)).json()["tenant_id"] == T_A
    assert c.get("/_probe/ctx", headers=_h(M_B)).json()["tenant_id"] == T_B


def test_cross_tenant_resource_is_404_not_403() -> None:  # AT-015
    c = _client()
    assert c.get("/_probe/docs/doc-a", headers=_h(M_A)).status_code == 200
    r = c.get("/_probe/docs/doc-b", headers=_h(M_A))
    assert r.status_code == 404 and r.json()["code"] == "RESOURCE_NOT_FOUND"
    assert c.get("/_probe/docs/missing", headers=_h(M_A)).status_code == 404
