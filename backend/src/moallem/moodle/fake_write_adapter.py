"""In-memory / fixture write adapter for unit and integration tests (Phase B).

Does not contact Moodle. Simulates create + verify with deterministic IDs and a real
read-back: verification reports what was actually "created", so tests can prove that
a mismatch is detected.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256

from moallem.moodle.client import MoodleClient
from moallem.moodle.errors import MoodleUnavailable
from moallem.moodle.write import (
    QuestionCreateSpec,
    QuizCreateRequest,
    QuizCreateResult,
    QuizVerification,
)


class FakeWriteAdapter:
    """Deterministic test double implementing MoodleWriteAdapter."""

    def __init__(
        self,
        *,
        fail_verify: bool = False,
        fail_create: bool = False,
        drop_questions: int = 0,
    ) -> None:
        self.fail_verify = fail_verify
        self.fail_create = fail_create
        self.drop_questions = drop_questions  # simulate Moodle storing fewer questions
        self.created: list[tuple[QuizCreateRequest, tuple[QuestionCreateSpec, ...]]] = []
        self._by_id: dict[int, tuple[QuizCreateRequest, int]] = {}
        self._by_key: dict[str, QuizCreateResult] = {}

    def create_quiz(
        self,
        client: MoodleClient,
        request: QuizCreateRequest,
        questions: Sequence[QuestionCreateSpec],
    ) -> QuizCreateResult:
        del client
        if self.fail_create:
            raise MoodleUnavailable("fake adapter forced create failure")
        # Idempotent on the operation key, like the real adapter's idnumber lookup.
        existing = self._by_key.get(request.external_operation_key)
        if existing is not None:
            return existing
        self.created.append((request, tuple(questions)))
        digest = sha256(request.external_operation_key.encode()).hexdigest()
        quiz_id = int(digest[:8], 16) % 1_000_000 + 10_000
        result = QuizCreateResult(
            moodle_quiz_id=quiz_id,
            moodle_cmid=quiz_id + 1,
            raw_reference=request.external_operation_key,
        )
        stored = max(len(questions) - self.drop_questions, 0)
        self._by_id[quiz_id] = (request, stored)
        self._by_key[request.external_operation_key] = result
        return result

    def verify_quiz(
        self,
        client: MoodleClient,
        *,
        course_id: str,
        moodle_quiz_id: int,
        expected_name: str,
        expected_question_count: int,
    ) -> QuizVerification:
        del client, expected_question_count
        now = datetime.now(UTC)
        entry = self._by_id.get(moodle_quiz_id)
        if self.fail_verify or entry is None:
            return QuizVerification(
                moodle_quiz_id=moodle_quiz_id,
                name_matches=False,
                question_count=0,
                course_id_matches=False,
                verified_at=now,
            )
        request, stored = entry
        return QuizVerification(
            moodle_quiz_id=moodle_quiz_id,
            name_matches=request.name.strip() == expected_name.strip(),
            question_count=stored,
            course_id_matches=request.course_id == course_id,
            verified_at=now,
        )
