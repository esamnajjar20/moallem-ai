import json
import logging
import sys

from moallem.logging import REDACTED, JsonFormatter, redact, redact_text, request_id_var


def _format(msg: str, **extra: object) -> dict[str, object]:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, (), None)
    for k, v in extra.items():
        setattr(record, k, v)
    data: dict[str, object] = json.loads(JsonFormatter("svc", "test").format(record))
    return data


def test_sensitive_keys_are_redacted_recursively() -> None:
    out = redact({"user": "a", "Authorization": "Bearer abc", "nested": {"api_key": "k", "n": 1}})
    assert out["Authorization"] == REDACTED
    assert out["nested"]["api_key"] == REDACTED
    assert out["nested"]["n"] == 1
    assert out["user"] == "a"


def test_url_credentials_and_bearer_tokens_are_scrubbed_from_text() -> None:
    assert "hunter2" not in redact_text("connect postgresql://app:hunter2@db:5432/x failed")
    assert "abc.def" not in redact_text("header Bearer abc.def rejected")


def test_log_line_is_json_with_request_id_and_redacted_extras() -> None:
    token = request_id_var.set("req_123")
    try:
        line = _format("hello", password="p", path="/x")  # noqa: S106
    finally:
        request_id_var.reset(token)
    assert line["request_id"] == "req_123"
    assert line["password"] == REDACTED
    assert line["path"] == "/x"
    assert line["service"] == "svc"


def test_exception_trace_is_scrubbed() -> None:
    try:
        raise RuntimeError("redis://u:secretpw@host/0")
    except RuntimeError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", (), sys.exc_info())
    out = JsonFormatter("svc", "test").format(record)
    assert "secretpw" not in out
    assert json.loads(out)["exc_type"] == "RuntimeError"
