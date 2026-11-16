"""Fail-closed HTTP placeholders for Moodle course reads."""

from typing import Annotated, Never
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from moallem.api.deps import get_membership_repo, get_user_id
from moallem.domain.membership import (
    ActiveContext,
    MembershipRepository,
    resolve_active_context,
)
from moallem.moodle.errors import MoodleUnavailable

router = APIRouter(tags=["courses"])


def get_course_active_context(
    user_id: Annotated[str, Depends(get_user_id)],
    repo: Annotated[MembershipRepository, Depends(get_membership_repo)],
    membership_id: Annotated[str, Header(alias="X-Active-Membership-ID")],
) -> ActiveContext:
    return resolve_active_context(
        authenticated_user_id=user_id,
        header_value=membership_id,
        repo=repo,
    )


def require_connection_repository(
    request: Request,
    _context: Annotated[ActiveContext, Depends(get_course_active_context)],
) -> None:
    if getattr(request.app.state, "moodle_connection_repository", None) is None:
        raise MoodleUnavailable("Moodle connection repository is not configured.")
    raise MoodleUnavailable("Moodle course reads are not configured.")


@router.get(
    "/courses",
    operation_id="listTeacherCourses",
    response_model=None,
    responses={503: {"description": "Moodle connection repository unavailable"}},
)
async def list_courses(
    _repository: Annotated[None, Depends(require_connection_repository)],
    connection_id: UUID,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Never:
    raise MoodleUnavailable("Moodle course reads are not configured.")


@router.get(
    "/courses/{course_id}/context",
    operation_id="getCourseContext",
    response_model=None,
    responses={503: {"description": "Moodle connection repository unavailable"}},
)
async def get_course_context(
    course_id: str,
    _repository: Annotated[None, Depends(require_connection_repository)],
    connection_id: UUID,
) -> Never:
    raise MoodleUnavailable("Moodle course reads are not configured.")
