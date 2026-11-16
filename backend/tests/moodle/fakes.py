import json
from collections.abc import Callable, Mapping
from typing import Any

from moallem.moodle.client import MoodleClient, Token, TransportResponse
from moallem.moodle.url_policy import ResolvedTarget, normalize_site_url

TOKEN = "tok_SECRET_0123456789abcdef"  # noqa: S105 - synthetic test value


class FakeResolver:
    def __init__(self, mapping: Mapping[str, list[str]] | None = None) -> None:
        self.mapping = dict(mapping or {})
        self.calls: list[str] = []

    def resolve(self, host: str) -> list[str]:
        self.calls.append(host)
        if host not in self.mapping:
            raise OSError("nxdomain")
        return self.mapping[host]


class FakeTransport:
    """Routes by wsfunction (or by path for downloads). Records everything it was asked to send."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.by_function: dict[str, Callable[[Mapping[str, str]], TransportResponse]] = {}
        self.by_path: dict[str, TransportResponse] = {}
        self.raise_exc: Exception | None = None
        self.raw: TransportResponse | None = None

    def json_for(self, function: str, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.by_function[function] = lambda form: TransportResponse(status, body)

    def post(
        self,
        *,
        target: ResolvedTarget,
        path: str,
        form: Mapping[str, str],
        timeout_s: float,
        max_bytes: int,
    ) -> TransportResponse:
        self.calls.append(
            {
                "target": target,
                "path": path,
                "form": dict(form),
                "timeout_s": timeout_s,
                "max_bytes": max_bytes,
            }
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.raw is not None:
            return self.raw
        if path in self.by_path:
            return self.by_path[path]
        fn = form.get("wsfunction", "")
        if fn in self.by_function:
            return self.by_function[fn](form)
        return TransportResponse(404, b"")


PUBLIC = {"moodle.example.edu": ["93.184.216.34"]}


def make_client(
    transport: FakeTransport | None = None,
    site: str = "https://moodle.example.edu",
    resolver: FakeResolver | None = None,
) -> tuple[MoodleClient, FakeTransport]:
    t = transport or FakeTransport()
    c = MoodleClient(
        site=normalize_site_url(site),
        token=Token(TOKEN),
        transport=t,
        resolver=resolver or FakeResolver(PUBLIC),
    )
    return c, t


SITE_INFO = {
    "sitename": "Example University",
    "username": "teacher1",
    "userid": 42,
    "siteurl": "https://moodle.example.edu",
    "release": "5.3.1 (Build: 20261112)",
    "version": "2026100501",
    "functions": [
        {"name": "core_webservice_get_site_info", "version": "2026100501"},
        {"name": "core_enrol_get_users_courses", "version": "2026100501"},
        {"name": "core_course_get_contents", "version": "2026100501"},
    ],
}
