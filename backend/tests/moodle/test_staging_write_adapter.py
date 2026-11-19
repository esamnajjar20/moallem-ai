"""StagingMoodleWriteAdapter against the recorded-style FakeTransport (no network)."""

import pytest

from moallem.moodle.errors import MoodleFunctionNotAvailable, MoodleResponseInvalid
from moallem.moodle.question_mapping import map_quiz_draft_to_specs
from moallem.moodle.staging_write_adapter import StagingMoodleWriteAdapter, StagingWriteConfig
from moallem.moodle.write import (
    UNKNOWN_QUESTION_COUNT,
    MoodlePartialWrite,
    QuizCreateRequest,
)
from tests.moodle.fakes import FakeTransport, make_client
from tests.worker.support import OPERATION_KEY, make_draft

CFG = StagingWriteConfig(
    create_quiz_function="local_create_quiz",
    add_questions_function="local_add_questions",
    verify_quiz_function="local_get_quiz",
)
REQUEST = QuizCreateRequest(
    course_id="12", name="اختبار الوحدة", intro="", external_operation_key=OPERATION_KEY
)


def _specs():  # type: ignore[no-untyped-def]
    return map_quiz_draft_to_specs(make_draft())[2]


def _wire(transport: FakeTransport) -> None:
    transport.json_for("local_create_quiz", {"quizid": 77, "cmid": 88})
    transport.json_for("local_add_questions", {"added": 2})


def _functions(transport: FakeTransport) -> list[str]:
    return [c["form"]["wsfunction"] for c in transport.calls]


def test_unconfigured_adapter_fails_closed() -> None:
    client, transport = make_client()
    with pytest.raises(MoodleFunctionNotAvailable):
        StagingMoodleWriteAdapter().create_quiz(client, REQUEST, _specs())
    assert transport.calls == []


def test_questions_are_really_sent_and_full_key_is_the_idnumber() -> None:
    client, transport = make_client()
    _wire(transport)
    result = StagingMoodleWriteAdapter(CFG).create_quiz(client, REQUEST, _specs())
    assert (result.moodle_quiz_id, result.moodle_cmid) == (77, 88)
    assert _functions(transport) == ["local_create_quiz", "local_add_questions"]
    create_form, add_form = transport.calls[0]["form"], transport.calls[1]["form"]
    assert create_form["idnumber"] == OPERATION_KEY  # not truncated
    assert add_form["quizid"] == "77"
    assert add_form["questions[0][qtype]"] == "multichoice"
    assert add_form["questions[1][name]"].startswith("Q-")


def test_failure_while_adding_questions_is_a_partial_write() -> None:
    client, transport = make_client()
    transport.json_for("local_create_quiz", {"quizid": 77})
    transport.json_for("local_add_questions", {"exception": "x", "errorcode": "boom"})
    with pytest.raises(MoodlePartialWrite):
        StagingMoodleWriteAdapter(CFG).create_quiz(client, REQUEST, _specs())


def test_response_without_quiz_id_is_rejected_not_guessed() -> None:
    client, transport = make_client()
    transport.json_for("local_create_quiz", {"id": 5, "cmid": 6})  # ambiguous keys
    with pytest.raises(MoodleResponseInvalid):
        StagingMoodleWriteAdapter(CFG).create_quiz(client, REQUEST, _specs())
    assert _functions(transport) == ["local_create_quiz"]


def test_existing_quiz_with_same_idnumber_is_reused() -> None:
    cfg = StagingWriteConfig(
        create_quiz_function="local_create_quiz",
        add_questions_function="local_add_questions",
        verify_quiz_function="local_get_quiz",
        find_quiz_function="local_find_quiz",
    )
    client, transport = make_client()
    _wire(transport)
    transport.json_for("local_find_quiz", [{"quizid": 99, "cmid": 100}])
    result = StagingMoodleWriteAdapter(cfg).create_quiz(client, REQUEST, _specs())
    assert result.moodle_quiz_id == 99
    assert _functions(transport) == ["local_find_quiz"]


def _verify(payload):  # type: ignore[no-untyped-def]
    client, transport = make_client()
    transport.json_for("local_get_quiz", payload)
    return StagingMoodleWriteAdapter(CFG).verify_quiz(
        client,
        course_id="12",
        moodle_quiz_id=77,
        expected_name=REQUEST.name,
        expected_question_count=2,
    )


def test_verify_reports_what_moodle_returned() -> None:
    good = _verify({"quizid": 77, "name": REQUEST.name, "course": 12, "questioncount": 2})
    assert good.matches(2)


def test_verify_without_question_count_never_verifies() -> None:
    v = _verify({"quizid": 77, "name": REQUEST.name, "course": 12})
    assert v.question_count == UNKNOWN_QUESTION_COUNT
    assert not v.matches(2)


@pytest.mark.parametrize(
    "payload",
    [
        {"quizid": 77, "name": "اسم آخر", "course": 12, "questioncount": 2},
        {"quizid": 77, "name": REQUEST.name, "course": 13, "questioncount": 2},
        {"quizid": 5, "name": REQUEST.name, "course": 12, "questioncount": 2},
        {"quizid": 77, "name": REQUEST.name, "questioncount": 2},
    ],
)
def test_verify_detects_name_course_or_id_mismatch(payload: dict[str, object]) -> None:
    assert not _verify(payload).matches(2)


def test_verify_wrong_question_count_is_detected() -> None:
    v = _verify({"quizid": 77, "name": REQUEST.name, "course": 12, "questioncount": 1})
    assert not v.matches(2)
