"""Moodle read operations (P3-01..03): site info / capability snapshot, teacher courses, course
contents and authorised file paths.

Output shapes follow contracts/openapi.draft.yaml (CourseSummary, CourseSection,
CourseModuleSummary) and tools moodle.discover_capabilities / list_teacher_courses /
get_course_contents. EVERYTHING returned from Moodle is UNTRUSTED text: HTML is reduced to plain
text and lengths are capped before anything can reach a model prompt.

OPEN (needs staging evidence, not guessable here):
- how to restrict `list_teacher_courses` to courses where the user is a teacher
  (core_enrol_get_users_courses returns every enrolment; no role field is returned);
- real shapes/limits of core_course_get_contents on the target version;
- whether pluginfile accepts the token in a POST body on the target site.
"""

import base64
import binascii
import hashlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from moallem.domain.errors import CursorInvalid
from moallem.moodle.client import MoodleClient
from moallem.moodle.errors import MoodlePermissionDenied, MoodleResponseInvalid, UnsafeMoodleUrl

FN_SITE_INFO = "core_webservice_get_site_info"
FN_USER_COURSES = "core_enrol_get_users_courses"
FN_COURSE_CONTENTS = "core_course_get_contents"
REQUIRED_READ_FUNCTIONS = (FN_SITE_INFO, FN_USER_COURSES, FN_COURSE_CONTENTS)

MAX_FUNCTIONS = 300  # tool_registry output maxItems
MAX_SECTIONS = 500
MAX_MODULES_PER_SECTION = 500
MAX_FILES_PER_MODULE = 200
MAX_TEXT = 2000
PAGE_SIZE_MAX = 100
_PLUGINFILE_SEGMENT = "/webservice/pluginfile.php/"
_FILE_NS = uuid.UUID("5f0b1b8e-6a53-5a4e-9d57-0d0c8f6f7a01")  # fixed namespace for source refs


# ---------------------------------------------------------------- helpers


class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag in ("br", "p", "div", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def strip_html(value: object, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        return ""
    p = _TextExtractor()
    try:
        p.feed(value)
        p.close()
    except Exception:
        return " ".join(value.split())[:limit]
    return " ".join("".join(p.parts).split())[:limit]


def _clean(value: object, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MoodleResponseInvalid(f"unexpected type for {field}")
    return value


def _list_of_dicts(value: object, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise MoodleResponseInvalid(f"unexpected shape for {field}")
    return value


def _iso(epoch: object) -> str | None:
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0:
        return None
    try:
        return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


# ---------------------------------------------------------------- site info / capabilities


@dataclass(frozen=True, slots=True)
class SiteInfo:
    site_name: str
    release: str
    version: str  # Moodle build number string, e.g. "2026100500"
    user_id: int
    username: str
    functions: tuple[str, ...]
    reported_site_url: str | None


def parse_site_info(raw: object) -> SiteInfo:
    if not isinstance(raw, dict):
        raise MoodleResponseInvalid("site info is not an object")
    fns = raw.get("functions")
    if not isinstance(fns, list):
        raise MoodleResponseInvalid("site info has no function list")
    names = sorted(
        {f["name"] for f in fns if isinstance(f, dict) and isinstance(f.get("name"), str)}
    )
    release, version = raw.get("release"), raw.get("version")
    if not isinstance(release, str) or not release or not isinstance(version, str) or not version:
        raise MoodleResponseInvalid("site info lacks release/version")
    reported = raw.get("siteurl")
    return SiteInfo(
        site_name=_clean(raw.get("sitename"), 255),
        release=_clean(release, 255),
        version=_clean(version, 255),
        user_id=_int(raw.get("userid"), "userid"),
        username=_clean(raw.get("username"), 100),
        functions=tuple(names[:MAX_FUNCTIONS]),
        reported_site_url=reported if isinstance(reported, str) else None,
    )


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    """Sanitised; contains no token and no personal data beyond the Moodle user id."""

    moodle_release: str
    moodle_build: str
    service_enabled: bool
    allowed_functions: tuple[str, ...]
    function_list_hash: str
    missing_required: tuple[str, ...]
    read_supported: bool
    moodle_user_id: int
    checked_at: str
    # Teacher role/capability evidence needs staging (P3-01); intentionally empty here.
    capabilities: tuple[str, ...] = ()


def discover_capabilities(
    client: MoodleClient, *, now: Callable[[], datetime] | None = None
) -> CapabilitySnapshot:
    info = parse_site_info(client.call(FN_SITE_INFO))
    clock = now or (lambda: datetime.now(UTC))
    missing = tuple(f for f in REQUIRED_READ_FUNCTIONS if f not in info.functions)
    digest = hashlib.sha256("\n".join(info.functions).encode()).hexdigest()
    return CapabilitySnapshot(
        moodle_release=info.release,
        moodle_build=info.version,
        service_enabled=True,  # a successful get_site_info proves the token/service pair works
        allowed_functions=info.functions,
        function_list_hash=digest,
        missing_required=missing,
        read_supported=not missing,
        moodle_user_id=info.user_id,
        checked_at=clock().astimezone(UTC).isoformat().replace("+00:00", "Z"),
    )


# ---------------------------------------------------------------- courses


@dataclass(frozen=True, slots=True)
class CourseSummary:
    course_id: str
    fullname: str
    shortname: str | None
    visible: bool | None
    start_date: str | None
    end_date: str | None

    def to_dict(self) -> dict[str, Any]:  # matches CourseSummary (visible is non-nullable)
        d: dict[str, Any] = {
            "course_id": self.course_id,
            "fullname": self.fullname,
            "shortname": self.shortname,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }
        if self.visible is not None:
            d["visible"] = self.visible
        return d


@dataclass(frozen=True, slots=True)
class CoursePage:
    items: tuple[CourseSummary, ...]
    has_more: bool
    next_cursor: str | None


def parse_courses(raw: object) -> list[CourseSummary]:
    out: dict[str, CourseSummary] = {}
    for c in _list_of_dicts(raw, "courses"):
        cid = str(_int(c.get("id"), "course id"))
        fullname = _clean(c.get("fullname") or c.get("displayname"), 255)
        if not fullname:
            continue  # contract requires fullname; skip rather than invent one
        vis = c.get("visible")
        out[cid] = CourseSummary(
            course_id=cid,
            fullname=fullname,
            shortname=_clean(c.get("shortname"), 100) or None,
            visible=bool(vis) if isinstance(vis, int) else None,
            start_date=_iso(c.get("startdate")),
            end_date=_iso(c.get("enddate")),
        )
    return sorted(out.values(), key=lambda x: (x.fullname.casefold(), int(x.course_id)))


def encode_offset_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def decode_offset_cursor(cursor: str | None) -> int:
    """Offset into the caller's OWN, stable-sorted course list. Forging it can only move the
    window inside data the caller may already read, so it is validated but not signed."""
    if cursor is None:
        return 0
    try:
        text = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise CursorInvalid("invalid cursor") from None
    head, _, num = text.partition(":")
    if head != "o" or not num.isascii() or not num.isdigit() or len(num) > 9:
        raise CursorInvalid("invalid cursor")
    return int(num)


def list_enrolled_courses(
    client: MoodleClient, *, moodle_user_id: int, cursor: str | None = None, page_size: int = 25
) -> CoursePage:
    """Return courses in which the connected Moodle principal is enrolled.

    Moodle's ``core_enrol_get_users_courses`` does not prove a teacher role. Callers must
    not present this result as teacher-only, and must independently verify course capabilities
    before enabling any write operation.
    """
    if not 1 <= page_size <= PAGE_SIZE_MAX:
        raise ValueError("page_size out of range")
    offset = decode_offset_cursor(cursor)
    courses = parse_courses(client.call(FN_USER_COURSES, {"userid": moodle_user_id}))
    page = courses[offset : offset + page_size]
    more = offset + page_size < len(courses)
    return CoursePage(
        items=tuple(page),
        has_more=more,
        next_cursor=encode_offset_cursor(offset + page_size) if more else None,
    )


def list_teacher_courses(
    client: MoodleClient, *, moodle_user_id: int, cursor: str | None = None, page_size: int = 25
) -> CoursePage:
    """Deprecated compatibility alias; result is enrolments, not verified teacher roles."""
    return list_enrolled_courses(
        client, moodle_user_id=moodle_user_id, cursor=cursor, page_size=page_size
    )


def require_course_enrollment(client: MoodleClient, *, moodle_user_id: int, course_id: str) -> None:
    """Fail closed unless the connected principal is enrolled in the requested course.

    This is an access-scope check, not proof of a teacher capability. Moodle writes remain
    separately disabled until capability verification and write adapters are approved.
    """
    courses = parse_courses(client.call(FN_USER_COURSES, {"userid": moodle_user_id}))
    if not any(course.course_id == course_id for course in courses):
        raise MoodlePermissionDenied("moodle principal is not enrolled in this course")


# ---------------------------------------------------------------- course contents / files


@dataclass(frozen=True, slots=True)
class FileRef:
    source_ref_id: str  # deterministic uuid5; stable across reads while the file is unchanged
    module_id: str
    filename: str
    filepath: str
    size: int | None
    mimetype: str | None
    modified_at: str | None
    download_path: str  # path under the site root; validated by file_download_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ref_id": self.source_ref_id,
            "module_id": self.module_id,
            "filename": self.filename,
            "filepath": self.filepath,
            "size": self.size,
            "mimetype": self.mimetype,
            "modified_at": self.modified_at,
        }


@dataclass(frozen=True, slots=True)
class ModuleSummary:
    module_id: str
    module_type: str
    name: str
    visible: bool
    url: str | None
    files: tuple[FileRef, ...] = ()

    def to_dict(self) -> dict[str, Any]:  # matches CourseModuleSummary
        return {
            "module_id": self.module_id,
            "module_type": self.module_type,
            "name": self.name,
            "visible": self.visible,
            "url": self.url,
            "source_ref_id": self.files[0].source_ref_id if self.files else None,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(frozen=True, slots=True)
class SectionSummary:
    section_id: str
    name: str
    visible: bool
    summary: str | None
    modules: tuple[ModuleSummary, ...]

    def to_dict(self) -> dict[str, Any]:  # matches CourseSection
        return {
            "section_id": self.section_id,
            "name": self.name,
            "visible": self.visible,
            "summary": self.summary,
            "modules": [m.to_dict() for m in self.modules],
        }


@dataclass(frozen=True, slots=True)
class CourseContents:
    course_id: str
    sections: tuple[SectionSummary, ...]
    truncated: bool


def _same_site_url(host: str, port: int, url: object) -> str | None:
    """Module links are shown to teachers; keep only plain https links to the connected site."""
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != host or (parts.port or 443) != port:
        return None
    if parts.username or parts.password or parts.fragment:
        return None
    return url


def file_download_path(client: MoodleClient, fileurl: object) -> str:
    """Return the path (under the site) of a Moodle-hosted file, or raise.

    Only https URLs on the connection's own host/port whose path is below
    `<base>/webservice/pluginfile.php/` are accepted: a hostile course cannot make the server
    fetch arbitrary URLs, nor send the token to another host.
    """
    if not isinstance(fileurl, str):
        raise UnsafeMoodleUrl("file_url_not_string")
    parts = urlsplit(fileurl)
    site = client.site
    if (
        parts.scheme != "https"
        or parts.hostname != site.host
        or (parts.port or 443) != site.port
        or parts.username
        or parts.password
        or parts.fragment
    ):
        raise UnsafeMoodleUrl("file_url_other_host")
    prefix = site.base_path + _PLUGINFILE_SEGMENT
    path = parts.path
    if not path.startswith(prefix) or ".." in path.split("/") or "%2e" in path.lower():
        raise UnsafeMoodleUrl("file_url_not_pluginfile")
    if parts.query:  # a token embedded in the stored URL must never be kept or reused
        raise UnsafeMoodleUrl("file_url_has_query")
    return path[len(site.base_path) :]


def fetch_file(client: MoodleClient, ref: FileRef, *, max_bytes: int) -> bytes:
    """Authorised download. Caller must already have tenant/permission-checked the connection."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    return client.download(ref.download_path, max_bytes=max_bytes)


def _parse_file(
    client: MoodleClient, connection_id: str, course_id: str, module_id: str, c: Mapping[str, Any]
) -> FileRef | None:
    if c.get("type") != "file":
        return None
    filename = _clean(c.get("filename"), 255)
    if not filename:
        return None
    try:
        path = file_download_path(client, c.get("fileurl"))
    except UnsafeMoodleUrl:
        return None  # drop files we could not fetch safely; never fail the whole course
    filepath = _clean(c.get("filepath"), 512) or "/"
    modified = c.get("timemodified")
    stable = f"{connection_id}|{course_id}|{module_id}|{filepath}|{filename}|{modified}"
    size = c.get("filesize")
    mime = c.get("mimetype")
    return FileRef(
        source_ref_id=str(uuid.uuid5(_FILE_NS, stable)),
        module_id=module_id,
        filename=filename,
        filepath=filepath,
        size=size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None,
        mimetype=_clean(mime, 127) or None if isinstance(mime, str) else None,
        modified_at=_iso(modified),
        download_path=path,
    )


def _visible(obj: Mapping[str, Any]) -> bool:
    v, uv = obj.get("visible"), obj.get("uservisible")
    base = bool(v) if isinstance(v, int) else True
    return base and (bool(uv) if isinstance(uv, int) else True)


def get_course_contents(
    client: MoodleClient,
    *,
    connection_id: str,
    course_id: str,
    include_file_metadata: bool = True,
) -> CourseContents:
    if not course_id.isascii() or not course_id.isdigit() or len(course_id) > 18:
        raise ValueError("course_id must be a Moodle numeric id")
    raw = _list_of_dicts(client.call(FN_COURSE_CONTENTS, {"courseid": int(course_id)}), "contents")
    truncated = len(raw) > MAX_SECTIONS
    sections: list[SectionSummary] = []
    for s in raw[:MAX_SECTIONS]:
        mods_raw = s.get("modules", [])
        mods_raw = _list_of_dicts(mods_raw, "modules") if mods_raw else []
        truncated = truncated or len(mods_raw) > MAX_MODULES_PER_SECTION
        mods: list[ModuleSummary] = []
        for m in mods_raw[:MAX_MODULES_PER_SECTION]:
            module_id = str(_int(m.get("id"), "module id"))
            files: list[FileRef] = []
            if include_file_metadata:
                contents = m.get("contents", [])
                contents = _list_of_dicts(contents, "module contents") if contents else []
                truncated = truncated or len(contents) > MAX_FILES_PER_MODULE
                for c in contents[:MAX_FILES_PER_MODULE]:
                    f = _parse_file(client, connection_id, course_id, module_id, c)
                    if f is not None:
                        files.append(f)
            mods.append(
                ModuleSummary(
                    module_id=module_id,
                    module_type=_clean(m.get("modname"), 64) or "unknown",
                    name=_clean(m.get("name"), 255),
                    visible=_visible(m),
                    url=_same_site_url(client.site.host, client.site.port, m.get("url")),
                    files=tuple(files),
                )
            )
        sections.append(
            SectionSummary(
                section_id=str(_int(s.get("id"), "section id")),
                name=_clean(s.get("name"), 255),
                visible=_visible(s),
                summary=strip_html(s.get("summary")) or None,
                modules=tuple(mods),
            )
        )
    return CourseContents(course_id=course_id, sections=tuple(sections), truncated=truncated)


def all_files(contents: CourseContents) -> Sequence[FileRef]:
    return [f for s in contents.sections for m in s.modules for f in m.files]
