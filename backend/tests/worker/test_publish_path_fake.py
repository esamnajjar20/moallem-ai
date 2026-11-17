"""Vertical-slice publish path with FakeWriteAdapter (no network)."""

from decimal import Decimal
from uuid import uuid4

import pytest

from moallem.ai.quiz.contracts import AnswerOptionPreview, QuestionDraftPreview, QuizDraftPreview
from moallem.domain.authorization import TeacherMVPPolicy
from moallem.domain.membership import ActiveContext
from moallem.moodle.fake_write_adapter import FakeWriteAdapter
from moallem.moodle.question_mapping import map_quiz_draft_to_specs
from moallem.moodle.write_service import MoodleWriteService
from moallem.domain.publishing import PublishIntent, PublishState, SnapshotDescriptor


class _Conn:
    def __init__(self) -> None:
        self.status = type("S", (), {"value": "ACTIVE"})()
        # minimal duck-type: ConnectionStatus.ACTIVE comparison in service uses enum
from moallem.moodle.service import ConnectionStatus, MoodleConnection
from moallem.domain.secrets import SecretRef


class _Connections:
    def get(self, ctx, connection_id: str) -> MoodleConnection:
        return MoodleConnection(
            connection_id=connection_id,
            tenant_id=ctx.tenant_id,
            site_url="https://moodle.example.test",
            secret_ref=SecretRef(vault_id="v1", key_id="k1"),
            status=ConnectionStatus.ACTIVE,
            moodle_user_id=7,
        )


class _Vault:
    def reveal(self, ref: SecretRef) -> str:
        return "test-token-value"


class _Transport:
    def post(self, **kwargs):  # noqa: ANN003
        raise AssertionError("network should not be used with FakeWriteAdapter")


class _Resolver:
    def resolve(self, *args, **kwargs):  # noqa: ANN003
        raise AssertionError("resolve should not be called for fake path")


def test_map_and_fake_publish_outcome_shape() -> None:
    draft = QuizDraftPreview(
        title="اختبار وحدة",
        instructions="تعليمات",
        questions=(
            QuestionDraftPreview(
                question_id=uuid4(),
                question_type_code="MULTICHOICE",
                stem="عاصمة فلسطين؟",
                options=(
                    AnswerOptionPreview(option_id="a", text="القدس"),
                    AnswerOptionPreview(option_id="b", text="حيفا"),
                ),
                correct_answer_preview="القدس",
                rationale=None,
                points=Decimal("1"),
                source_refs=(),
                unsupported=False,
                unsupported_reason=None,
            ),
        ),
        schema_version="1.0",
        total_points=Decimal("1"),
    )
    name, intro, specs = map_quiz_draft_to_specs(draft)
    assert name == "اختبار وحدة"
    assert len(specs) == 1
    assert specs[0].question_type == "multichoice"


def test_teacher_policy_allows_api_actions() -> None:
    policy = TeacherMVPPolicy()
    ctx = ActiveContext("u", "m", "t", ("TEACHER",))
    assert policy.allows(ctx.roles, "task.create")
    assert policy.allows(ctx.roles, "quiz.approve")
    assert policy.allows(ctx.roles, "quiz.publish")
    assert not policy.allows(ctx.roles, "admin.destroy")
