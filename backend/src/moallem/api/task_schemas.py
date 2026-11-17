"""Task request/response schemas kept in parity with the OpenAPI draft."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from moallem.domain.tasks import TaskStatus

_QUESTION_TYPE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_LOCALE = r"^[a-z]{2,3}(-[A-Z]{2})?$"


class QuizSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    question_count: int = Field(ge=1, le=100)
    question_types: list[str] | None = Field(default=None, min_length=1, max_length=10)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    maximum_grade: float | None = Field(default=None, gt=0)
    language: str | None = Field(default=None, pattern=_LOCALE)
    instructions: str | None = Field(default=None, max_length=4000)

    @field_validator("question_types")
    @classmethod
    def _question_types_are_unique_and_well_formed(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is not None and (
            len(value) != len(set(value))
            or any(not _QUESTION_TYPE.fullmatch(item) for item in value)
        ):
            raise ValueError("question_types must be unique uppercase identifiers")
        return value


class ClientMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_channel: Literal["ANDROID", "IOS", "WEB", "UNKNOWN"] | None = None
    device_locale: str | None = Field(default=None, max_length=32)
    client_version: str | None = Field(default=None, max_length=64)


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: Literal["CREATE_QUIZ"]
    connection_id: UUID
    course_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=10000)
    quiz_spec: QuizSpec | None = None
    source_refs: list[UUID] | None = Field(default=None, max_length=100)
    locale: str | None = Field(default=None, pattern=_LOCALE)
    client_metadata: ClientMetadata | None = None


class CreateTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    task_status: Literal["RECEIVED"]
    status_url: str
    events_url: str | None = None
    created_at: datetime | None = None
    request_id: str


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    task_status: TaskStatus
    current_step: str | None = None
    updated_at: datetime
    cancel_requested: bool = False


class TaskEventType(StrEnum):
    TASK_CREATED = "TASK_CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    INPUT_REQUIRED = "INPUT_REQUIRED"
    DRAFT_READY = "DRAFT_READY"
    VALIDATION_COMPLETED = "VALIDATION_COMPLETED"
    APPROVAL_RECORDED = "APPROVAL_RECORDED"
    PUBLISH_PREPARED = "PUBLISH_PREPARED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    EXTERNAL_DISPATCHED = "EXTERNAL_DISPATCHED"
    EXTERNAL_STEP_SUCCEEDED = "EXTERNAL_STEP_SUCCEEDED"
    EXTERNAL_STEP_FAILED = "EXTERNAL_STEP_FAILED"
    EXTERNAL_OUTCOME_UNKNOWN = "EXTERNAL_OUTCOME_UNKNOWN"
    RECONCILIATION_UPDATED = "RECONCILIATION_UPDATED"
    TASK_RECOVERED = "TASK_RECOVERED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"


class TaskEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    sequence: int = Field(ge=1)
    event_type: TaskEventType
    from_status: TaskStatus | None = None
    to_status: TaskStatus | None = None
    message_code: str | None = None
    occurred_at: datetime


class TaskEventPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskEventItem]
    next_cursor: str | None
    has_more: bool
    oldest_available_sequence: int = Field(ge=1)


class TaskSnapshotDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    course_id: str = Field(min_length=1, max_length=128)


class TaskSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    version_no: int = Field(ge=1)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    destination: TaskSnapshotDestination
    schema_version: str = Field(min_length=1, max_length=128)
    content: dict[str, object]
    quality_report: dict[str, object]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    snapshot_id: UUID
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    comment: str | None = Field(default=None, max_length=2000)


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    approval_id: UUID
    decision: Literal["APPROVED", "REJECTED"]
    snapshot_id: UUID
    decided_at: datetime
    expires_at: datetime


class TaskResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_object_type: Literal["QUIZ"]
    external_object_id: str = Field(min_length=1, max_length=512)
    verification_status: Literal["VERIFIED"]
    verified_at: datetime
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    course_id: str = Field(min_length=1, max_length=128)
    expected_content_match: Literal[True]
