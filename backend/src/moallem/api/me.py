"""GET /api/v1/me (UNRUN, needs fastapi). Only operation exempt from X-Active-Membership-ID."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from moallem.api.deps import get_membership_repo, get_user_id
from moallem.domain.membership import MembershipRepository

router = APIRouter(prefix="/api/v1")


@router.get("/me")
async def me(
    user_id: Annotated[str, Depends(get_user_id)],
    repo: Annotated[MembershipRepository, Depends(get_membership_repo)],
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "memberships": [
            {
                "membership_id": m.membership_id,
                "tenant_id": m.tenant_id,
                "roles": list(m.roles),
                "status": m.status.value,
            }
            for m in repo.list_for_user(user_id)
        ],
    }
