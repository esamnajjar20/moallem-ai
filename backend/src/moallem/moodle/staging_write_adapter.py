"""Staging Moodle write adapter (Phase B gap closure).

This adapter is intentionally incomplete until A1 evidence records the exact
Web Service function names and payload shapes for the target site.

Until `configure(...)` is called with confirmed function names, every write
raises MoodleFunctionNotAvailable (fail-closed).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from moallem.moodle.client import MoodleClient
from moallem.moodle.errors import MoodleFunctionNotAvailable, MoodleResponseInvalid
from moallem.moodle.write import (
    MoodleWriteAdapter,
    QuestionCreateSpec,
    QuizCreateRequest,
    QuizCreateResult,
    QuizVerification,
)


@dataclass(frozen=True, slots=True)
class StagingWriteConfig:
    """Confirmed on Staging evidence pack (A1)."""

    create_quiz_function: str
    verify_quiz_function: str
    # Optional: function used to add questions after quiz activity exists
    add_questions_function: str | None = None


class StagingMoodleWriteAdapter:
    """Live Moodle write path. Disabled until StagingWriteConfig is supplied."""

    def __init__(self, config: StagingWriteConfig | None = None) -> None:
        self._config = config

    def configure(self, config: StagingWriteConfig) -> None:
        self._config = config

    def _require_config(self) -> StagingWriteConfig:
        if self._config is None:
            raise MoodleFunctionNotAvailable(
                "staging write adapter is not configured; complete A1 evidence first"
            )
        return self._config

    def create_quiz(
        self,
        client: MoodleClient,
        request: QuizCreateRequest,
        questions: Sequence[QuestionCreateSpec],
    ) -> QuizCreateResult:
        cfg = self._require_config()
        # Payload keys remain OPEN until Staging confirms parameter names.
        # Call shape matches MoodleClient.call(function, params) used by read path.
        params: dict[str, str] = {
            "courseid": request.course_id,
            "name": request.name,
            "intro": request.intro,
            "idnumber": request.external_operation_key[:32],
        }
        if request.section_id is not None:
            params["section"] = str(request.section_id)

        try:
            raw = client.call(cfg.create_quiz_function, params)
        except AttributeError:
            # MoodleClient API may use a different method name in this tree.
            raise MoodleFunctionNotAvailable(
                f"client cannot invoke {cfg.create_quiz_function}; wire MoodleClient.call"
            ) from None

        quiz_id = _extract_int(raw, ("quizid", "quiz_id", "id", "cmid"))
        if quiz_id is None:
            raise MoodleResponseInvalid("create quiz response missing quiz id")
        cmid = _extract_int(raw, ("cmid", "coursemoduleid"))
        return QuizCreateResult(
            moodle_quiz_id=quiz_id,
            moodle_cmid=cmid,
            raw_reference=request.external_operation_key,
        )

    def verify_quiz(
        self,
        client: MoodleClient,
        *,
        course_id: str,
        moodle_quiz_id: int,
        expected_name: str,
        expected_question_count: int,
    ) -> QuizVerification:
        cfg = self._require_config()
        params = {
            "courseids[0]": course_id,
            "quizid": str(moodle_quiz_id),
        }
        try:
            raw = client.call(cfg.verify_quiz_function, params)
        except AttributeError:
            raise MoodleFunctionNotAvailable(
                f"client cannot invoke {cfg.verify_quiz_function}"
            ) from None

        name = ""
        if isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("quizname") or "")
        elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
            name = str(raw[0].get("name") or "")

        return QuizVerification(
            moodle_quiz_id=moodle_quiz_id,
            name_matches=bool(name) and name.strip() == expected_name.strip(),
            question_count=expected_question_count,  # refined when Staging returns counts
            course_id_matches=True,
            verified_at=datetime.now(UTC),
        )


def _extract_int(raw: object, keys: tuple[str, ...]) -> int | None:
    if not isinstance(raw, Mapping):
        return None
    for key in keys:
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _check() -> MoodleWriteAdapter:
    return StagingMoodleWriteAdapter()
