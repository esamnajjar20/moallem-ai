"""Contract-compatible asynchronous task endpoints."""

import base64
import binascii
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from moallem.api.deps import get_membership_repo, get_user_id
from moallem.api.task_schemas import (
    CreateTaskRequest,
    CreateTaskResponse,
    TaskEventItem,
    TaskEventPage,
    TaskStatusResponse,
)
from moallem.domain.authorization import DenyAllPolicy, PermissionPolicy, authorize
from moallem.domain.events import decode_cursor, encode_cursor
from moallem.domain.membership import (
    ActiveContext,
    MembershipRepository,
    resolve_active_context,
)
from moallem.moodle.errors import ConnectionNotActive
from moallem.moodle.service import ConnectionStatus
from moallem.persistence.task_repository import PostgresTaskRepository

router = APIRouter()


def get_task_active_context(
    user_id: Annotated[str, Depends(get_user_id)],
    repo: Annotated[MembershipRepository, Depends(get_membership_repo)],
    membership_id: Annotated[str, Header(alias="X-Active-Membership-ID")],
) -> ActiveContext:
    return resolve_active_context(
        authenticated_user_id=user_id,
        header_value=membership_id,
        repo=repo,
    )


def _encoded_key(value: str | None) -> bytes:
    if value is None:
        raise HTTPException(status_code=503, detail="task service not configured")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(status_code=503, detail="task service not configured") from None


def _task_repository(request: Request) -> PostgresTaskRepository:
    repository: PostgresTaskRepository | None = request.app.state.task_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="task service not configured")
    return repository


def _authorize(request: Request, context: ActiveContext, action: str) -> None:
    policy: PermissionPolicy = request.app.state.permission_policy or DenyAllPolicy()
    authorize(context, action, context.tenant_id, policy)


@router.post("/tasks", status_code=202, response_model=CreateTaskResponse)
def create_task(
    payload: CreateTaskRequest,
    request: Request,
    context: Annotated[ActiveContext, Depends(get_task_active_context)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=22, max_length=200)],
) -> CreateTaskResponse:
    _authorize(request, context, "task.create")
    repository = _task_repository(request)
    settings = request.app.state.settings
    retention = settings.idempotency_retention_seconds
    if retention is None:
        raise HTTPException(status_code=503, detail="task service not configured")
    key = _encoded_key(
        settings.idempotency_hmac_key.get_secret_value()
        if settings.idempotency_hmac_key is not None
        else None
    )
    connections = request.app.state.moodle_connection_repository
    if connections is None:
        raise HTTPException(status_code=503, detail="task service not configured")
    connection = connections.get(context, str(payload.connection_id))
    if connection.status is not ConnectionStatus.ACTIVE or connection.moodle_user_id is None:
        raise ConnectionNotActive("connection is not active")

    task_id = str(uuid.uuid4())
    request_payload = payload.model_dump(mode="json", exclude_none=True)
    result = repository.create_idempotent(
        context,
        task_id=task_id,
        task_type=payload.task_type,
        connection_id=str(payload.connection_id),
        course_id=payload.course_id,
        prompt=payload.prompt,
        request_payload=request_payload,
        idempotency_key=idempotency_key,
        idempotency_hmac_key=key,
        idempotency_retention_seconds=retention,
    )
    request_id = getattr(request.state, "request_id", "")
    return CreateTaskResponse(
        task_id=uuid.UUID(result.task.task_id),
        task_status="RECEIVED",
        status_url=f"/api/v1/tasks/{result.task.task_id}",
        events_url=f"/api/v1/tasks/{result.task.task_id}/events",
        created_at=result.task.created_at,
        request_id=request_id,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: uuid.UUID,
    request: Request,
    context: Annotated[ActiveContext, Depends(get_task_active_context)],
) -> TaskStatusResponse:
    _authorize(request, context, "task.read")
    task = _task_repository(request).get(context, str(task_id))
    return TaskStatusResponse(
        task_id=uuid.UUID(task.task_id),
        task_status=task.status,
        updated_at=task.updated_at,
        cancel_requested=task.cancel_requested,
    )


@router.get("/tasks/{task_id}/events", response_model=TaskEventPage)
def get_task_events(
    task_id: uuid.UUID,
    request: Request,
    context: Annotated[ActiveContext, Depends(get_task_active_context)],
    cursor: Annotated[str | None, Query(min_length=16, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> TaskEventPage:
    _authorize(request, context, "task.read")
    repository = _task_repository(request)
    key = _encoded_key(
        request.app.state.settings.event_cursor_hmac_key.get_secret_value()
        if request.app.state.settings.event_cursor_hmac_key is not None
        else None
    )
    task_id_value = str(task_id)
    after = (
        decode_cursor(
            cursor,
            key=key,
            tenant_id=context.tenant_id,
            task_id=task_id_value,
            actor_membership_id=context.membership_id,
        )
        if cursor is not None
        else None
    )
    page = repository.list_event_page(context, task_id_value, after_sequence=after, limit=limit)
    next_cursor = (
        encode_cursor(
            key=key,
            tenant_id=context.tenant_id,
            task_id=task_id_value,
            last_sequence=page.last_sequence,
            actor_membership_id=context.membership_id,
        )
        if page.has_more
        else None
    )
    return TaskEventPage(
        items=[
            TaskEventItem(
                event_id=uuid.UUID(event.event_id),
                sequence=event.sequence,
                event_type=event.event_type,
                from_status=event.from_status,
                to_status=event.to_status,
                message_code=event.message_code,
                occurred_at=event.occurred_at,
            )
            for event in page.items
        ],
        next_cursor=next_cursor,
        has_more=page.has_more,
        oldest_available_sequence=page.oldest_available_sequence,
    )
