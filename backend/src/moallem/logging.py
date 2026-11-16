"""Structured JSON logging with redaction. Stdlib only.

Covers the P1 slice of the observability spec: JSON logs with request_id and no secrets.
OpenTelemetry is out of scope for P1.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

REDACTED = "[REDACTED]"

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|authorization|api[-_]?key|cookie|credential|idempotency)",
    re.IGNORECASE,
)
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+(:[^/\s@]*)?@")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def redact_text(text: str) -> str:
    text = _URL_CREDENTIALS.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", text)
    return _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)


def redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_text(str(value))


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, env: str) -> None:
        super().__init__()
        self._service = service
        self._env = env

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "service": self._service,
            "env": self._env,
            "request_id": request_id_var.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                payload[k] = redact(v, k)
        if record.exc_info:
            exc_type = record.exc_info[0]
            payload["exc_type"] = exc_type.__name__ if exc_type else None
            payload["exc_trace"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str, service: str, env: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service=service, env=env))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
