import json
import subprocess
import sys
from pathlib import Path

from moallem.moodle.read import FN_COURSE_CONTENTS, FN_SITE_INFO, FN_USER_COURSES

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_moodle_fixtures.py"


def test_sanitized_fixture_replays_without_network(tmp_path: Path) -> None:
    fixture = {
        "schema_version": 1,
        "site_url": "https://moodle.example.edu",
        "responses": {
            FN_SITE_INFO: {
                "userid": 1,
                "release": "sanitized",
                "version": "202611",
                "functions": [
                    {"name": fn} for fn in (FN_SITE_INFO, FN_USER_COURSES, FN_COURSE_CONTENTS)
                ],
            },
            FN_USER_COURSES: [{"id": 42, "fullname": "Sanitized course"}],
            FN_COURSE_CONTENTS: [{"id": 0, "name": "General", "modules": []}],
        },
    }
    fixture_path = tmp_path / "response.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - invoke this repository's fixed fixture harness
        [sys.executable, str(_SCRIPT), str(fixture_path), "--course-id", "42"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Sanitized course" in result.stdout
    assert "fixture-replay-only" not in result.stdout
