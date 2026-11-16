"""Domain exceptions: each carries the stable ErrorCode and the contract HTTP status."""

from moallem.errors import ErrorCode


class DomainError(Exception):
    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status: int = 500

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code.value)


class MembershipContextRequired(DomainError):
    code = ErrorCode.MEMBERSHIP_CONTEXT_REQUIRED
    http_status = 400


class MembershipContextInvalid(DomainError):
    code = ErrorCode.MEMBERSHIP_CONTEXT_INVALID
    http_status = 400


class TaskStateConflict(DomainError):
    code = ErrorCode.TASK_STATE_CONFLICT
    http_status = 409


class EventCursorExpired(DomainError):
    code = ErrorCode.EVENT_CURSOR_EXPIRED
    http_status = 410


class CursorInvalid(DomainError):
    code = ErrorCode.VALIDATION_FAILED
    http_status = 400


class NotCanonicalizable(DomainError):
    code = ErrorCode.VALIDATION_FAILED
    http_status = 400
