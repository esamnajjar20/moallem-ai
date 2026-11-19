"""The payload the Flutter client sends must be accepted by the API schema.

Keep in sync with ``mobile/lib/features/quiz/data/quiz_repository.dart`` (requestGeneration).
"""

from pathlib import Path

from moallem.api.task_schemas import CreateTaskRequest

MOBILE_REPOSITORY = (
    Path(__file__).resolve().parents[2] / "mobile/lib/features/quiz/data/quiz_repository.dart"
)


def test_flutter_create_task_payload_matches_schema() -> None:
    payload = {
        "task_type": "CREATE_QUIZ",
        "connection_id": "00000000-0000-4000-8000-0000000000c1",
        "course_id": "12",
        "prompt": "Generate quiz: اختبار",
        "quiz_spec": {
            "name": "اختبار",
            "question_count": 5,
            "question_types": ["MULTICHOICE", "TRUEFALSE"],
            "language": "ar",
        },
        "locale": "ar",
        "client_metadata": {"source_channel": "ANDROID"},
    }
    request = CreateTaskRequest.model_validate(payload)
    assert request.quiz_spec is not None
    assert request.quiz_spec.question_count == 5


def test_flutter_client_sends_the_keys_this_test_models() -> None:
    source = MOBILE_REPOSITORY.read_text(encoding="utf-8")
    keys = ("'task_type'", "'connection_id'", "'course_id'", "'quiz_spec'", "'Idempotency-Key'")
    for key in keys:
        assert key in source
