import json
import pickle

import pytest

from moallem.moodle.client import MoodleClient, Token, TransportResponse, flatten_params
from moallem.moodle.errors import (
    MoodleCredentialInvalid,
    MoodleFunctionNotAvailable,
    MoodlePermissionDenied,
    MoodleResponseInvalid,
    MoodleUnavailable,
    UnsafeMoodleUrl,
)
from tests.moodle.fakes import PUBLIC, TOKEN, FakeResolver, make_client


def test_flatten_params_moodle_array_syntax() -> None:
    assert flatten_params({"a": 1, "b": True, "c": [10, 20], "d": [{"x": "y"}]}) == {
        "a": "1",
        "b": "1",
        "c[0]": "10",
        "c[1]": "20",
        "d[0][x]": "y",
    }
    with pytest.raises(ValueError):
        flatten_params({"a": None})


def test_call_posts_token_in_body_never_in_path() -> None:
    c, t = make_client()
    t.json_for("core_webservice_get_site_info", {"ok": 1})
    assert c.call("core_webservice_get_site_info", {"userid": 5}) == {"ok": 1}
    call = t.calls[0]
    assert call["path"] == "/webservice/rest/server.php" and TOKEN not in call["path"]
    assert call["form"]["wstoken"] == TOKEN and call["form"]["userid"] == "5"
    assert call["form"]["moodlewsrestformat"] == "json"
    assert call["target"].ip == "93.184.216.34" and call["timeout_s"] == 15.0


def test_base_path_is_prefixed() -> None:
    c, t = make_client(site="https://moodle.example.edu/lms")
    t.json_for("core_webservice_get_site_info", [])
    c.call("core_webservice_get_site_info")
    assert t.calls[0]["path"] == "/lms/webservice/rest/server.php"


@pytest.mark.parametrize("bad", ["", "Core_x", "core x", "core_x;rm", "a", "x" * 200, "../x"])
def test_invalid_function_names_rejected(bad: str) -> None:
    c, _ = make_client()
    with pytest.raises(ValueError):
        c.call(bad)


def test_token_never_leaks_via_repr_str_pickle_or_client_repr() -> None:
    tok = Token(TOKEN)
    c, _ = make_client()
    for text in (repr(tok), str(tok), repr(c), f"{tok}", f"{c}"):
        assert TOKEN not in text
    with pytest.raises(TypeError):
        pickle.dumps(tok)


@pytest.mark.parametrize("bad", ["", "has space", "tab\there", "ключ"])
def test_token_format_validated(bad: str) -> None:
    with pytest.raises(MoodleCredentialInvalid):
        Token(bad)


@pytest.mark.parametrize(
    ("errorcode", "exc"),
    [
        ("invalidtoken", MoodleCredentialInvalid),
        ("nopermissions", MoodlePermissionDenied),
        ("required_capability_exception", MoodlePermissionDenied),
        ("accessexception", MoodleFunctionNotAvailable),
        ("somethingelse", MoodleUnavailable),
        (None, MoodleUnavailable),
    ],
)
def test_remote_errors_mapped_and_message_discarded(errorcode: str | None, exc: type) -> None:
    c, t = make_client()
    payload = {"exception": "x", "message": f"bad wstoken={TOKEN}"}
    if errorcode:
        payload["errorcode"] = errorcode
    t.json_for("core_webservice_get_site_info", payload)
    with pytest.raises(exc) as ei:
        c.call("core_webservice_get_site_info")
    assert type(ei.value) is exc and TOKEN not in str(ei.value) and TOKEN not in repr(ei.value)


def test_unknown_remote_code_kept_only_if_safe() -> None:
    c, t = make_client()
    t.json_for("core_webservice_get_site_info", {"exception": "x", "errorcode": "weird_code"})
    with pytest.raises(MoodleUnavailable) as ei:
        c.call("core_webservice_get_site_info")
    assert ei.value.remote_errorcode == "weird_code"
    bad = {"exception": "x", "errorcode": "Bad Code!<script>"}
    t.json_for("core_webservice_get_site_info", bad)
    with pytest.raises(MoodleUnavailable) as ei2:
        c.call("core_webservice_get_site_info")
    assert ei2.value.remote_errorcode is None


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 404, 429, 500, 503])
def test_http_failures_and_redirects_not_followed(status: int) -> None:
    c, t = make_client()
    t.raw = TransportResponse(status, b"")
    with pytest.raises(MoodleUnavailable):
        c.call("core_webservice_get_site_info")
    assert len(t.calls) == 1  # no redirect followed, no retry inside the client


@pytest.mark.parametrize("exc", [TimeoutError(), ConnectionResetError(), OSError("boom")])
def test_transport_errors_become_unavailable_without_cause_leak(exc: Exception) -> None:
    c, t = make_client()
    t.raise_exc = exc
    with pytest.raises(MoodleUnavailable) as ei:
        c.call("core_webservice_get_site_info")
    assert ei.value.__cause__ is None and TOKEN not in str(ei.value)


def test_non_json_and_oversize_responses_rejected() -> None:
    c, t = make_client()
    t.raw = TransportResponse(200, b"<html>login</html>")
    with pytest.raises(MoodleResponseInvalid):
        c.call("core_webservice_get_site_info")
    big = MoodleClient(
        site=c.site,
        token=Token(TOKEN),
        transport=t,
        resolver=FakeResolver(PUBLIC),
        max_response_bytes=10,
    )
    t.raw = TransportResponse(200, json.dumps({"a": "x" * 50}).encode())
    with pytest.raises(MoodleResponseInvalid):
        big.call("core_webservice_get_site_info")


def test_every_call_re_resolves_and_blocks_a_rebound_host() -> None:
    res = FakeResolver(PUBLIC)
    c, t = make_client(resolver=res)
    t.json_for("core_webservice_get_site_info", [])
    c.call("core_webservice_get_site_info")
    res.mapping["moodle.example.edu"] = ["127.0.0.1"]
    with pytest.raises(UnsafeMoodleUrl):
        c.call("core_webservice_get_site_info")
    assert len(t.calls) == 1  # the second request never left the process
