"""Domain exceptions: each carries the stable ErrorCode and the contract HTTP status."""

from moallem.errors import ErrorCode


class DomainError(Exception):
    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status: int = 500

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code.value)


class AuthenticationRequired(DomainError):
    code = ErrorCode.AUTHENTICATION_REQUIRED
    http_status = 401


class MembershipContextRequired(DomainError):
    code = ErrorCode.MEMBERSHIP_CONTEXT_REQUIRED
    http_status = 400


class MembershipContextInvalid(DomainError):
    # Planning_Closure_Decisions_v2.4 (DEC-039): foreign / non-ACTIVE membership => 403.
    # Missing or malformed header stays 400 (MembershipContextRequired).
    code = ErrorCode.MEMBERSHIP_CONTEXT_INVALID
    http_status = 403


class MembershipContextMalformed(DomainError):
    # Closure Decisions v2.4: malformed header is a format error (400/422), not a 403.
    code = ErrorCode.VALIDATION_FAILED
    http_status = 400


class PermissionDenied(DomainError):
    code = ErrorCode.PERMISSION_DENIED
    http_status = 403


class ResourceNotFound(DomainError):
    code = ErrorCode.RESOURCE_NOT_FOUND
    http_status = 404


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
