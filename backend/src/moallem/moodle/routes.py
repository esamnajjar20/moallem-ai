"""Fail-closed HTTP placeholders for Moodle course reads."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request

from moallem.api.deps import get_membership_repo, get_user_id
from moallem.domain.membership import (
    ActiveContext,
    MembershipRepository,
    resolve_active_context,
)
from moallem.moodle.errors import MoodleUnavailable
from moallem.moodle.service import MoodleReadService

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


def get_moodle_read_service(
    request: Request,
    _context: Annotated[ActiveContext, Depends(get_course_active_context)],
) -> MoodleReadService:
    service = getattr(request.app.state, "moodle_read_service", None)
    if not isinstance(service, MoodleReadService):
        raise MoodleUnavailable("Moodle read service is not configured.")
    return service


@router.get(
    "/courses",
    operation_id="listTeacherCourses",
    response_model=None,
    responses={503: {"description": "Moodle connection repository unavailable"}},
)
def list_courses(
    service: Annotated[MoodleReadService, Depends(get_moodle_read_service)],
    context: Annotated[ActiveContext, Depends(get_course_active_context)],
    connection_id: UUID,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    page = service.list_courses(
        context,
        str(connection_id),
        cursor=cursor,
        page_size=limit,
    )
    return {
        "items": [item.to_dict() for item in page.items],
        "has_more": page.has_more,
        "next_cursor": page.next_cursor,
    }


@router.get(
    "/courses/{course_id}/context",
    operation_id="getCourseContext",
    response_model=None,
    responses={503: {"description": "Moodle connection repository unavailable"}},
)
def get_course_context(
    course_id: Annotated[str, Path(min_length=1, max_length=128)],
    service: Annotated[MoodleReadService, Depends(get_moodle_read_service)],
    context: Annotated[ActiveContext, Depends(get_course_active_context)],
    connection_id: UUID,
) -> dict[str, Any]:
    contents = service.course_contents(context, str(connection_id), course_id)
    return {
        "course_id": contents.course_id,
        "sections": [section.to_dict() for section in contents.sections],
        "source_refs": [],
    }
