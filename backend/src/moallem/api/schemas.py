"""Transport schemas used in P1. Mirrors ErrorEnvelope in contracts/openapi.draft.yaml."""

from pydantic import BaseModel, ConfigDict, Field

from moallem.errors import ErrorCode


class FieldError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    code: str
    message: str | None = None


class ErrorDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_errors: list[FieldError] | None = None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(max_length=500)
    details: ErrorDetails | None = None
    request_id: str
    retryable: bool
    retry_after_seconds: int | None = Field(default=None, ge=0)
