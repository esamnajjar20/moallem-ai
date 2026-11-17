import base64
from datetime import UTC, datetime
from typing import Any

import pytest

from moallem.domain.errors import CursorInvalid
from moallem.moodle.client import TransportResponse
from moallem.moodle.errors import MoodleResponseInvalid, UnsafeMoodleUrl
from moallem.moodle.read import (
    all_files,
    decode_offset_cursor,
    discover_capabilities,
    encode_offset_cursor,
    fetch_file,
    file_download_path,
    get_course_contents,
    list_teacher_courses,
    parse_site_info,
    strip_html,
)
from tests.moodle.fakes import SITE_INFO, TOKEN, make_client

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
PF = "https://moodle.example.edu/webservice/pluginfile.php/55/mod_resource/content/1/notes.pdf"


# ------------------------------------------------------------ capabilities


def test_discover_capabilities_snapshot_is_sanitised_and_hashed() -> None:
    c, t = make_client()
    t.json_for("core_webservice_get_site_info", SITE_INFO)
    s = discover_capabilities(c, now=lambda: NOW)
    assert s.moodle_release.startswith("5.3.1") and s.moodle_build == "2026100501"
    assert s.read_supported and s.missing_required == () and s.service_enabled
    assert s.allowed_functions == tuple(sorted(f["name"] for f in SITE_INFO["functions"]))
    assert len(s.function_list_hash) == 64 and s.checked_at == "2026-11-16T12:00:00Z"
    assert s.moodle_user_id == 42 and s.capabilities == ()
    assert TOKEN not in repr(s)


def test_missing_required_function_is_reported_not_assumed() -> None:
    c, t = make_client()
    info = {**SITE_INFO, "functions": [{"name": "core_webservice_get_site_info"}]}
    t.json_for("core_webservice_get_site_info", info)
    s = discover_capabilities(c, now=lambda: NOW)
    assert not s.read_supported
    assert set(s.missing_required) == {"core_enrol_get_users_courses", "core_course_get_contents"}


def test_function_hash_is_order_independent_and_changes_with_list() -> None:
    c, t = make_client()
    t.json_for("core_webservice_get_site_info", SITE_INFO)
    h1 = discover_capabilities(c, now=lambda: NOW).function_list_hash
    fns = SITE_INFO["functions"]
    t.json_for("core_webservice_get_site_info", {**SITE_INFO, "functions": fns[::-1]})
    assert discover_capabilities(c, now=lambda: NOW).function_list_hash == h1
    t.json_for("core_webservice_get_site_info", {**SITE_INFO, "functions": fns[:2]})
    assert discover_capabilities(c, now=lambda: NOW).function_list_hash != h1


@pytest.mark.parametrize(
    "bad",
    [
        [],
        "x",
        {},
        {**SITE_INFO, "functions": "nope"},
        {**SITE_INFO, "release": ""},
        {**SITE_INFO, "userid": "42"},
        {**SITE_INFO, "userid": True},
        {**SITE_INFO, "version": None},
    ],
)
def test_malformed_site_info_rejected(bad: Any) -> None:
    with pytest.raises(MoodleResponseInvalid):
        parse_site_info(bad)


# ------------------------------------------------------------ courses

COURSES = [
    {
        "id": 3,
        "fullname": "  Physics   101 ",
        "shortname": "PHY101",
        "visible": 1,
        "startdate": 1767225600,
        "enddate": 0,
    },
    {"id": 1, "fullname": "algebra", "shortname": "", "visible": 0},
    {"id": 2, "displayname": "Biology", "visible": 1},
    {"id": 9, "fullname": ""},  # unusable: skipped, not invented
    {"id": 3, "fullname": "Physics 101 (dup)"},  # duplicate id: last wins, listed once
]


def test_courses_are_normalised_sorted_and_deduplicated() -> None:
    c, t = make_client()
    t.json_for("core_enrol_get_users_courses", COURSES)
    page = list_teacher_courses(c, moodle_user_id=42)
    assert [x.course_id for x in page.items] == ["1", "2", "3"]
    first, _, third = page.items
    assert first.visible is False and first.shortname is None and first.start_date is None
    assert third.fullname == "Physics 101 (dup)"
    assert t.calls[0]["form"]["userid"] == "42"


def test_course_dto_matches_contract_shape() -> None:
    c, t = make_client()
    t.json_for("core_enrol_get_users_courses", [COURSES[0], {"id": 5, "fullname": "No vis"}])
    items = list_teacher_courses(c, moodle_user_id=42).items
    d0 = next(i for i in items if i.course_id == "3").to_dict()
    assert d0["visible"] is True and d0["start_date"] == "2026-01-01T00:00:00Z"
    assert d0["end_date"] is None
    assert "visible" not in next(i for i in items if i.course_id == "5").to_dict()


def test_pagination_has_no_gaps_or_duplicates() -> None:
    c, t = make_client()
    t.json_for(
        "core_enrol_get_users_courses",
        [{"id": i, "fullname": f"Course {i:02d}"} for i in range(1, 8)],
    )
    seen, cursor = [], None
    while True:
        p = list_teacher_courses(c, moodle_user_id=1, cursor=cursor, page_size=3)
        seen += [x.course_id for x in p.items]
        if not p.has_more:
            assert p.next_cursor is None
            break
        cursor = p.next_cursor
    assert seen == [str(i) for i in range(1, 8)]


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "!!",
        "bw",
        _b64("x:1"),
        _b64("o:-1"),
        _b64("o:abc"),
        _b64("o:"),
        _b64("o:" + "9" * 12),
        encode_offset_cursor(0) + "x",
    ],
)
def test_bad_cursor_rejected(bad: str) -> None:
    with pytest.raises(CursorInvalid):
        decode_offset_cursor(bad)


@pytest.mark.parametrize("size", [0, -1, 101])
def test_page_size_bounds(size: int) -> None:
    c, _ = make_client()
    with pytest.raises(ValueError):
        list_teacher_courses(c, moodle_user_id=1, page_size=size)


def test_non_list_course_response_rejected() -> None:
    c, t = make_client()
    t.json_for("core_enrol_get_users_courses", {"courses": []})
    with pytest.raises(MoodleResponseInvalid):
        list_teacher_courses(c, moodle_user_id=1)


# ------------------------------------------------------------ contents / files

CONTENTS = [
    {
        "id": 10,
        "name": "Week 1",
        "visible": 1,
        "summary": "<p>Intro <b>text</b></p><script>alert(1)</script><style>x{}</style>",
        "modules": [
            {
                "id": 100,
                "modname": "resource",
                "name": "Notes",
                "visible": 1,
                "url": "https://moodle.example.edu/mod/resource/view.php?id=100",
                "contents": [
                    {
                        "type": "file",
                        "filename": "notes.pdf",
                        "filepath": "/",
                        "filesize": 1234,
                        "mimetype": "application/pdf",
                        "timemodified": 1767225600,
                        "fileurl": PF,
                    },
                    {
                        "type": "file",
                        "filename": "evil.pdf",
                        "fileurl": "https://evil.example.com/x.pdf",
                    },
                    {"type": "url", "filename": "link", "fileurl": "https://x.example.com"},
                    {"type": "file", "filename": "tok.pdf", "fileurl": PF + "?token=LEAK"},
                ],
            },
            {
                "id": 101,
                "modname": "quiz",
                "name": "Quiz 1",
                "visible": 0,
                "url": "https://evil.example.com/phish",
            },
            {
                "id": 102,
                "modname": "page",
                "name": "Hidden by availability",
                "visible": 1,
                "uservisible": 0,
            },
        ],
    },
    {"id": 11, "name": "Week 2", "visible": 0, "summary": "", "modules": []},
]


def _contents(**kw: Any):  # type: ignore[no-untyped-def]
    c, t = make_client()
    t.json_for("core_course_get_contents", kw.pop("payload", CONTENTS))
    return get_course_contents(c, connection_id="conn-1", course_id="7", **kw), c, t


def test_contents_structure_and_visibility() -> None:
    res, _, t = _contents()
    assert t.calls[0]["form"]["courseid"] == "7"
    s1, s2 = res.sections
    assert (s1.section_id, s1.name, s1.visible) == ("10", "Week 1", True)
    assert s2.visible is False and s2.summary is None
    notes, quiz, page = s1.modules
    assert (notes.module_type, notes.visible) == ("resource", True)
    assert quiz.visible is False and page.visible is False  # uservisible=0 hides it
    assert not res.truncated


def test_html_summary_reduced_to_plain_text_without_script_or_style() -> None:
    res, *_ = _contents()
    assert res.sections[0].summary == "Intro text"
    assert strip_html("<p>a</p><p>b</p>") == "a b" and strip_html(None) == ""
    assert strip_html("<<<broken") != ""  # malformed markup never raises


def test_only_same_site_module_links_kept() -> None:
    res, *_ = _contents()
    notes, quiz, _ = res.sections[0].modules
    assert notes.url and notes.url.startswith("https://moodle.example.edu/")
    assert quiz.url is None


def test_only_safe_same_host_files_survive_and_tokens_never_stored() -> None:
    res, *_ = _contents()
    files = all_files(res)
    assert [f.filename for f in files] == ["notes.pdf"]
    f = files[0]
    assert f.download_path == "/webservice/pluginfile.php/55/mod_resource/content/1/notes.pdf"
    assert f.size == 1234 and f.mimetype == "application/pdf"
    assert "token" not in repr(f).lower() and "LEAK" not in repr(res)


def test_source_ref_is_deterministic_and_connection_scoped() -> None:
    a, *_ = _contents()
    b, *_ = _contents()
    assert all_files(a)[0].source_ref_id == all_files(b)[0].source_ref_id
    c, t = make_client()
    t.json_for("core_course_get_contents", CONTENTS)
    other = get_course_contents(c, connection_id="conn-2", course_id="7")
    assert all_files(other)[0].source_ref_id != all_files(a)[0].source_ref_id


def test_include_file_metadata_false_skips_files() -> None:
    res, *_ = _contents(include_file_metadata=False)
    assert all_files(res) == []


def test_file_provenance_serializes_safe_metadata_without_download_path() -> None:
    res, *_ = _contents()
    module = res.sections[0].modules[0]
    payload = module.to_dict()
    assert payload["source_ref_id"] == all_files(res)[0].source_ref_id
    assert payload["files"][0]["filename"] == "notes.pdf"
    assert "download_path" not in payload["files"][0]
    assert "token" not in repr(payload).lower()


def test_to_dict_matches_contract_section_shape() -> None:
    res, *_ = _contents()
    d = res.sections[0].to_dict()
    assert set(d) == {"section_id", "name", "visible", "summary", "modules"}
    assert set(d["modules"][0]) == {
        "module_id",
        "module_type",
        "name",
        "visible",
        "url",
        "source_ref_id",
        "files",
    }


@pytest.mark.parametrize("cid", ["", "abc", "1;2", "-1", "1 2", "9" * 30])
def test_course_id_must_be_numeric(cid: str) -> None:
    c, _ = make_client()
    with pytest.raises(ValueError):
        get_course_contents(c, connection_id="c", course_id=cid)


@pytest.mark.parametrize(
    "bad", [{"x": 1}, [1], [{"id": "x", "modules": []}], [{"id": 1, "modules": [{"id": "x"}]}]]
)
def test_malformed_contents_rejected(bad: Any) -> None:
    c, t = make_client()
    t.json_for("core_course_get_contents", bad)
    with pytest.raises(MoodleResponseInvalid):
        get_course_contents(c, connection_id="c", course_id="1")


def test_oversized_course_is_truncated_and_flagged() -> None:
    big = [{"id": i, "name": f"s{i}", "modules": []} for i in range(1, 600)]
    res, *_ = _contents(payload=big)
    assert len(res.sections) == 500 and res.truncated


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/webservice/pluginfile.php/1/a",
        "http://moodle.example.edu/webservice/pluginfile.php/1/a",
        "https://moodle.example.edu:8443/webservice/pluginfile.php/1/a",
        "https://user@moodle.example.edu/webservice/pluginfile.php/1/a",
        "https://moodle.example.edu/pluginfile.php/1/a",
        "https://moodle.example.edu/webservice/pluginfile.php/../../config.php",
        "https://moodle.example.edu/webservice/pluginfile.php/%2e%2e/x",
        "https://moodle.example.edu/webservice/pluginfile.php/1/a?token=x",
        "https://moodle.example.edu/webservice/pluginfile.php/1/a#f",
        None,
        5,
    ],
)
def test_file_download_path_rejects_anything_off_site(url: Any) -> None:
    c, _ = make_client()
    with pytest.raises(UnsafeMoodleUrl):
        file_download_path(c, url)


def test_file_download_respects_base_path() -> None:
    c, _ = make_client(site="https://moodle.example.edu/lms")
    ok = "https://moodle.example.edu/lms/webservice/pluginfile.php/1/a.txt"
    assert file_download_path(c, ok) == "/webservice/pluginfile.php/1/a.txt"
    with pytest.raises(UnsafeMoodleUrl):
        file_download_path(c, "https://moodle.example.edu/webservice/pluginfile.php/1/a.txt")


def test_fetch_file_sends_token_in_body_and_enforces_cap() -> None:
    res, c, t = _contents()
    ref = all_files(res)[0]
    t.by_path[c.site.base_path + ref.download_path] = TransportResponse(200, b"PDFDATA")
    assert fetch_file(c, ref, max_bytes=100) == b"PDFDATA"
    call = t.calls[-1]
    assert call["form"] == {"token": TOKEN} and call["max_bytes"] == 100
    assert "token" not in call["path"]
    t.by_path[c.site.base_path + ref.download_path] = TransportResponse(200, b"x" * 101)
    with pytest.raises(MoodleResponseInvalid):
        fetch_file(c, ref, max_bytes=100)
    with pytest.raises(ValueError):
        fetch_file(c, ref, max_bytes=0)
