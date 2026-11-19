"""Staging Moodle write adapter (Phase B gap closure).

Web Service function names and parameter keys are OPEN until the A1 staging evidence pack
records them. Until a ``StagingWriteConfig`` is supplied every call fails closed with
``MoodleFunctionNotAvailable``.

Safety properties (independent of the final parameter names):
- every question is actually sent; a failure after the quiz exists raises
  ``MoodlePartialWrite`` so the caller records an UNKNOWN outcome instead of retrying;
- the full operation key is the quiz ``idnumber`` and, when ``find_quiz_function`` is
  configured, an existing quiz with that idnumber is reused instead of duplicated;
- ``verify_quiz`` only reports what Moodle returned: a missing name, course or question
  count never verifies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from moallem.moodle.client import MoodleClient
from moallem.moodle.errors import MoodleFunctionNotAvailable, MoodleResponseInvalid
from moallem.moodle.write import (
    UNKNOWN_QUESTION_COUNT,
    MoodlePartialWrite,
    QuestionCreateSpec,
    QuizCreateRequest,
    QuizCreateResult,
    QuizVerification,
)


@dataclass(frozen=True, slots=True)
class StagingWriteConfig:
    """Confirmed on the Staging evidence pack (A1)."""

    create_quiz_function: str
    add_questions_function: str
    verify_quiz_function: str
    # Optional lookup by idnumber to make create idempotent across retries/reconciliation.
    find_quiz_function: str | None = None
    quiz_id_key: str = "quizid"
    cmid_key: str = "cmid"
    question_count_key: str = "questioncount"


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
        if not questions:
            raise MoodleResponseInvalid("refusing to create a quiz without questions")

        existing = self._find_existing(client, cfg, request)
        if existing is not None:
            return existing

        params: dict[str, Any] = {
            "courseid": request.course_id,
            "name": request.name,
            "intro": request.intro,
            # Full key (sha256 hex, 64 chars): truncating it would break idempotency.
            "idnumber": request.external_operation_key,
        }
        if request.section_id is not None:
            params["section"] = request.section_id

        raw = client.call(cfg.create_quiz_function, params)
        quiz_id = _extract_int(raw, cfg.quiz_id_key)
        if quiz_id is None:
            raise MoodleResponseInvalid("create quiz response missing quiz id")
        cmid = _extract_int(raw, cfg.cmid_key)

        try:
            client.call(
                cfg.add_questions_function,
                {"quizid": quiz_id, "questions": [_question_payload(q) for q in questions]},
            )
        except Exception as exc:
            raise MoodlePartialWrite(
                "quiz was created but adding questions did not complete"
            ) from exc

        return QuizCreateResult(
            moodle_quiz_id=quiz_id,
            moodle_cmid=cmid,
            raw_reference=request.external_operation_key,
        )

    def _find_existing(
        self, client: MoodleClient, cfg: StagingWriteConfig, request: QuizCreateRequest
    ) -> QuizCreateResult | None:
        if cfg.find_quiz_function is None:
            return None
        raw = client.call(
            cfg.find_quiz_function,
            {"courseid": request.course_id, "idnumber": request.external_operation_key},
        )
        item = _first_mapping(raw)
        if item is None:
            return None
        quiz_id = _extract_int(item, cfg.quiz_id_key)
        if quiz_id is None:
            return None
        return QuizCreateResult(
            moodle_quiz_id=quiz_id,
            moodle_cmid=_extract_int(item, cfg.cmid_key),
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
        del expected_question_count  # the caller compares; we only report what Moodle says
        cfg = self._require_config()
        raw = client.call(
            cfg.verify_quiz_function,
            {"courseids": [course_id], "quizid": moodle_quiz_id},
        )
        item = _first_mapping(raw)
        if item is None:
            raise MoodleResponseInvalid("verify response has no quiz object")

        returned_id = _extract_int(item, cfg.quiz_id_key)
        if returned_id is None:
            returned_id = _extract_int(item, "id")
        name = str(item.get("name") or item.get("quizname") or "")
        returned_course = item.get("course", item.get("courseid"))
        count = _extract_int(item, cfg.question_count_key)

        return QuizVerification(
            moodle_quiz_id=moodle_quiz_id,
            name_matches=(
                returned_id == moodle_quiz_id
                and bool(name)
                and name.strip() == expected_name.strip()
            ),
            question_count=UNKNOWN_QUESTION_COUNT if count is None else count,
            course_id_matches=(
                returned_course is not None and str(returned_course) == str(course_id)
            ),
            verified_at=datetime.now(UTC),
        )


def _question_payload(spec: QuestionCreateSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "qtype": spec.question_type,
        "name": spec.name,
        "questiontext": spec.text,
        "defaultmark": str(spec.default_mark),
    }
    if spec.general_feedback:
        payload["generalfeedback"] = spec.general_feedback
    if spec.options:
        payload["answers"] = [
            {"text": o.text, "fraction": str(o.fraction)} for o in spec.options
        ]
    elif spec.correct_answer is not None:
        payload["correctanswer"] = spec.correct_answer
    return payload


def _first_mapping(raw: object) -> Mapping[str, Any] | None:
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, list) and raw and isinstance(raw[0], Mapping):
        return raw[0]
    return None


def _extract_int(raw: object, key: str) -> int | None:
    if not isinstance(raw, Mapping):
        return None
    value = raw.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
