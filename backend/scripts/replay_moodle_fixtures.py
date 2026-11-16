#!/usr/bin/env python3
"""Replay sanitized Moodle JSON responses through the read adapter without network access."""

import argparse
import json
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from moallem.moodle.client import MoodleClient, Token, TransportResponse
from moallem.moodle.read import (
    FN_COURSE_CONTENTS,
    FN_SITE_INFO,
    FN_USER_COURSES,
    discover_capabilities,
    get_course_contents,
    list_teacher_courses,
)
from moallem.moodle.url_policy import ResolvedTarget, normalize_site_url

_REQUIRED = {FN_SITE_INFO, FN_USER_COURSES, FN_COURSE_CONTENTS}
_SYNTHETIC_TOKEN = "fixture-replay-only"  # noqa: S105 - fixture transport never sends it
_SYNTHETIC_IP = "93.184.216.34"
_DEFAULT_CONNECTION_ID = "00000000-0000-4000-8000-000000000001"


class FixtureResolver:
    def resolve(self, _host: str) -> list[str]:
        return [_SYNTHETIC_IP]


class FixtureTransport:
    def __init__(self, responses: Mapping[str, Any]) -> None:
        self._responses = responses

    def post(
        self,
        *,
        target: ResolvedTarget,
        path: str,
        form: Mapping[str, str],
        timeout_s: float,
        max_bytes: int,
    ) -> TransportResponse:
        del target, path, timeout_s, max_bytes
        function = form.get("wsfunction")
        if function not in self._responses:
            raise ValueError(f"fixture has no response for {function!r}")
        return TransportResponse(200, json.dumps(self._responses[function]).encode("utf-8"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="sanitized fixture JSON file")
    parser.add_argument("--course-id", required=True, help="synthetic Moodle course id")
    parser.add_argument("--connection-id", default=_DEFAULT_CONNECTION_ID)
    parser.add_argument("--cursor")
    parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("Unable to read a valid fixture JSON file.", file=sys.stderr)
        return 2
    if not isinstance(fixture, dict) or fixture.get("schema_version") != 1:
        print("Fixture must be an object with schema_version: 1.", file=sys.stderr)
        return 2
    responses = fixture.get("responses")
    if not isinstance(responses, dict) or not _REQUIRED.issubset(responses):
        print("Fixture responses must include all three Moodle read functions.", file=sys.stderr)
        return 2
    site_url = fixture.get("site_url")
    if not isinstance(site_url, str):
        print("Fixture must include a sanitized site_url.", file=sys.stderr)
        return 2
    site_info = responses[FN_SITE_INFO]
    if not isinstance(site_info, dict) or site_info.get("userid") != 1:
        print("Replace the Moodle user id with the synthetic integer 1.", file=sys.stderr)
        return 2
    try:
        connection_id = str(uuid.UUID(args.connection_id))
        client = MoodleClient(
            site=normalize_site_url(site_url),
            token=Token(_SYNTHETIC_TOKEN),
            transport=FixtureTransport(responses),
            resolver=FixtureResolver(),
        )
        capabilities = discover_capabilities(client)
        courses = list_teacher_courses(
            client,
            moodle_user_id=capabilities.moodle_user_id,
            cursor=args.cursor,
            page_size=args.limit,
        )
        contents = get_course_contents(
            client,
            connection_id=connection_id,
            course_id=args.course_id,
        )
    except (TypeError, ValueError) as exc:
        print(f"Fixture replay rejected: {exc}", file=sys.stderr)
        return 2

    output = {
        "capabilities": {
            "moodle_release": capabilities.moodle_release,
            "moodle_build": capabilities.moodle_build,
            "allowed_functions": capabilities.allowed_functions,
            "missing_required": capabilities.missing_required,
            "read_supported": capabilities.read_supported,
        },
        "courses": {
            "items": [item.to_dict() for item in courses.items],
            "has_more": courses.has_more,
            "next_cursor": courses.next_cursor,
        },
        "course_context": {
            "course_id": contents.course_id,
            "sections": [section.to_dict() for section in contents.sections],
            "truncated": contents.truncated,
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
