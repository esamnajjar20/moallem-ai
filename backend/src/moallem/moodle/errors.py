"""Moodle adapter errors. HTTP statuses for MOODLE_* codes are PROPOSED (the OpenAPI draft names
the codes but does not map them to statuses); confirm before freezing the contract."""

import re

from moallem.domain.errors import DomainError
from moallem.errors import ErrorCode

_SAFE_REMOTE_CODE = re.compile(r"[a-z0-9_]{1,64}")


class UnsafeMoodleUrl(DomainError):
    """Site URL rejected by the SSRF policy. `reason` is for audit logs, never for clients."""

    code = ErrorCode.VALIDATION_FAILED
    http_status = 422

    def __init__(self, reason: str) -> None:
        super().__init__("moodle site URL is not allowed")
        self.reason = reason


class ConnectionNotActive(DomainError):
    code = ErrorCode.CONNECTION_NOT_ACTIVE
    http_status = 409


class MoodleCredentialInvalid(DomainError):
    code = ErrorCode.MOODLE_CREDENTIAL_INVALID
    http_status = 422


class MoodleFunctionNotAvailable(DomainError):
    code = ErrorCode.MOODLE_FUNCTION_NOT_AVAILABLE
    http_status = 422


class MoodlePermissionDenied(DomainError):
    code = ErrorCode.MOODLE_PERMISSION_DENIED
    http_status = 403


class MoodleUnavailable(DomainError):
    """Network failure, timeout, 5xx, oversized/malformed response or unmapped remote error."""

    code = ErrorCode.MOODLE_UNAVAILABLE
    http_status = 503

    def __init__(self, message: str = "", *, remote_errorcode: str | None = None) -> None:
        super().__init__(message or "moodle is unavailable")
        # Sanitised: only [a-z0-9_]{1,64}; the remote message is NEVER kept (may echo secrets).
        self.remote_errorcode = (
            remote_errorcode
            if remote_errorcode is not None and _SAFE_REMOTE_CODE.fullmatch(remote_errorcode)
            else None
        )


class MoodleResponseInvalid(MoodleUnavailable):
    """Response parsed but does not have the shape the adapter requires."""
