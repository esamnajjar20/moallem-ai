"""In-memory / fixture write adapter for unit and integration tests (Phase B).

Does not contact Moodle. Simulates create + verify with deterministic IDs.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256

from moallem.moodle.client import MoodleClient
from moallem.moodle.write import (
    MoodleWriteAdapter,
    QuestionCreateSpec,
    QuizCreateRequest,
    QuizCreateResult,
    QuizVerification,
)


class FakeWriteAdapter:
    """Deterministic test double implementing MoodleWriteAdapter."""

    def __init__(self, *, fail_verify: bool = False, fail_create: bool = False) -> None:
        self.fail_verify = fail_verify
        self.fail_create = fail_create
        self.created: list[tuple[QuizCreateRequest, tuple[QuestionCreateSpec, ...]]] = []
        self._next_id = 10_000

    def create_quiz(
        self,
        client: MoodleClient,
        request: QuizCreateRequest,
        questions: Sequence[QuestionCreateSpec],
    ) -> QuizCreateResult:
        del client
        if self.fail_create:
            from moallem.moodle.errors import MoodleUnavailable

            raise MoodleUnavailable("fake adapter forced create failure")
        self.created.append((request, tuple(questions)))
        # Deterministic id from operation key so retries look idempotent in tests
        digest = sha256(request.external_operation_key.encode()).hexdigest()
        quiz_id = int(digest[:8], 16) % 1_000_000 + self._next_id
        cmid = quiz_id + 1
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
        del client, expected_question_count
        if self.fail_verify:
            return QuizVerification(
                moodle_quiz_id=moodle_quiz_id,
                name_matches=False,
                question_count=0,
                course_id_matches=False,
                verified_at=datetime.now(UTC),
            )
        return QuizVerification(
            moodle_quiz_id=moodle_quiz_id,
            name_matches=True,
            question_count=expected_question_count if not self.fail_verify else 0,
            course_id_matches=bool(course_id),
            verified_at=datetime.now(UTC),
        )


# Protocol compliance helper for type checkers
def _check_protocol() -> MoodleWriteAdapter:
    return FakeWriteAdapter()
