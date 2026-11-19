"""Shared fakes for publish-path tests (no network, no database)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from moallem.ai.quiz.contracts import AnswerOptionPreview, QuestionDraftPreview, QuizDraftPreview
from moallem.domain.authorization import PermissionPolicy, TeacherMVPPolicy
from moallem.domain.membership import (
    ActiveContext,
    InMemoryMembershipRepository,
    Membership,
    MembershipStatus,
)
from moallem.domain.publishing import PublishState
from moallem.domain.secrets import InMemoryVault
from moallem.domain.tasks import TaskStatus
from moallem.moodle.service import ConnectionStatus, MoodleConnection, new_connection_repository
from moallem.moodle.write import MoodleWriteAdapter
from moallem.moodle.write_service import MoodleWriteService
from moallem.persistence.publishing_repository import PublishIntentRecord, SnapshotRecord
from moallem.persistence.task_repository import PersistedTask
from moallem.worker.actor import ActorContextResolver
from moallem.worker.handlers.publish_quiz import PublishQuizHandler
from tests.moodle.fakes import PUBLIC, TOKEN, FakeResolver, FakeTransport

TENANT = "00000000-0000-4000-8000-0000000000aa"
MEMBERSHIP = "00000000-0000-4000-8000-000000000001"
TASK_ID = "00000000-0000-4000-8000-0000000000f1"
CONNECTION_ID = "00000000-0000-4000-8000-0000000000c1"
SNAPSHOT_ID = "00000000-0000-4000-8000-0000000000d1"
INTENT_ID = "00000000-0000-4000-8000-0000000000e1"
SNAPSHOT_HASH = "a" * 64
OPERATION_KEY = "b" * 64
COURSE_ID = "12"

ACTOR = ActiveContext("u1", MEMBERSHIP, TENANT, ("TEACHER",))


def make_draft(question_count: int = 2) -> QuizDraftPreview:
    questions = tuple(
        QuestionDraftPreview(
            question_id=uuid4(),
            question_type_code="MULTICHOICE",
            stem=f"سؤال {i}",
            options=(
                AnswerOptionPreview(option_id="a", text="الخيار أ"),
                AnswerOptionPreview(option_id="b", text="الخيار ب"),
            ),
            correct_answer_preview="a",
            rationale=None,
            points=Decimal(1),
            source_refs=(),
            unsupported=False,
            unsupported_reason=None,
        )
        for i in range(question_count)
    )
    return QuizDraftPreview(
        title="اختبار الوحدة",
        instructions="أجب عن كل الأسئلة",
        questions=questions,
        schema_version="1.0",
        total_points=Decimal(question_count),
    )


def make_snapshot(draft: QuizDraftPreview | None = None, **overrides: Any) -> SnapshotRecord:
    draft = draft or make_draft()
    fields: dict[str, Any] = {
        "snapshot_id": SNAPSHOT_ID,
        "tenant_id": TENANT,
        "task_id": TASK_ID,
        "version_no": 1,
        "snapshot_hash": SNAPSHOT_HASH,
        "schema_version": "1.0",
        "destination": {"connection_id": CONNECTION_ID, "course_id": COURSE_ID},
        "content": {"preview": draft.model_dump(mode="json")},
        "quality_report": {},
        "created_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return SnapshotRecord(**fields)


def make_task(status: TaskStatus = TaskStatus.APPROVED) -> PersistedTask:
    now = datetime.now(UTC)
    return PersistedTask(
        task_id=TASK_ID,
        tenant_id=TENANT,
        actor_membership_id=MEMBERSHIP,
        task_type="CREATE_QUIZ",
        connection_id=CONNECTION_ID,
        course_id=COURSE_ID,
        prompt="p",
        request_payload={},
        status=status,
        cancel_requested=False,
        external_dispatched=False,
        latest_event_sequence=0,
        created_at=now,
        updated_at=now,
    )


@dataclass
class FakeGateway:
    """Records the order of ledger calls exactly like the Postgres repository is driven."""

    snapshot: SnapshotRecord = field(default_factory=make_snapshot)
    dispatch_error: Exception | None = None
    intent_hash: str = SNAPSHOT_HASH
    intent_snapshot_id: str = SNAPSHOT_ID
    calls: list[str] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    completed: dict[str, Any] | None = None

    def create_publish_intent_for_worker(self, *, tenant_id: str, task_id: str) -> Any:
        self.calls.append("intent")
        return PublishIntentRecord(
            publish_intent_id=INTENT_ID,
            tenant_id=tenant_id,
            task_id=task_id,
            snapshot_id=self.intent_snapshot_id,
            snapshot_hash=self.intent_hash,
            external_operation_key=OPERATION_KEY,
            state=PublishState.PREPARED,
        )

    def get_current_snapshot(self, ctx: ActiveContext, task_id: str) -> SnapshotRecord:
        del ctx, task_id
        self.calls.append("snapshot")
        return self.snapshot

    def plan_external_step(self, **kwargs: Any) -> str:
        self.calls.append("plan")
        return "step-key-1"

    def mark_step_dispatched(self, **kwargs: Any) -> int:
        self.calls.append("dispatch")
        if self.dispatch_error is not None:
            raise self.dispatch_error
        return 1

    def record_step_outcome(self, **kwargs: Any) -> object:
        self.calls.append(f"outcome:{kwargs['outcome']}")
        self.outcomes.append(kwargs)
        return object()

    def begin_verification(self, **kwargs: Any) -> None:
        self.calls.append("verifying")

    def complete_verified_publish(self, **kwargs: Any) -> None:
        self.calls.append("completed")
        self.completed = kwargs


class FakeContext:
    def __init__(self) -> None:
        self.transitions: list[TaskStatus] = []

    async def transition(self, status: TaskStatus, **kwargs: Any) -> None:
        del kwargs
        self.transitions.append(status)


def make_service(
    adapter: MoodleWriteAdapter,
    *,
    policy: PermissionPolicy | None = None,
    status: ConnectionStatus = ConnectionStatus.ACTIVE,
) -> MoodleWriteService:
    vault, repo = InMemoryVault(), new_connection_repository()
    ref = vault.put(ACTOR, TOKEN)
    repo.add(
        ACTOR,
        MoodleConnection(CONNECTION_ID, TENANT, "https://moodle.example.edu", ref, status, 42),
    )
    return MoodleWriteService(
        connections=repo,
        vault=vault,
        policy=policy or TeacherMVPPolicy(),
        transport=FakeTransport(),
        resolver=FakeResolver(PUBLIC),
        write_adapter=adapter,
    )


def make_handler(
    gateway: FakeGateway,
    adapter: MoodleWriteAdapter,
    *,
    policy: PermissionPolicy | None = None,
    membership_status: MembershipStatus = MembershipStatus.ACTIVE,
) -> PublishQuizHandler:
    memberships = InMemoryMembershipRepository(
        {MEMBERSHIP: Membership(MEMBERSHIP, "u1", TENANT, ("TEACHER",), membership_status)}
    )
    return PublishQuizHandler(
        write_service=make_service(adapter, policy=policy),
        publications=gateway,
        actors=ActorContextResolver(memberships),
    )
