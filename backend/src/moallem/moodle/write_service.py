"""Moodle write orchestration (Phase B).

Performs the same fail-closed checks as MoodleReadService, then delegates the
actual side effect to an injected MoodleWriteAdapter.

Create and verify are separate calls so the worker can persist the create outcome in the
publish ledger *before* it starts verification (an ambiguous create must never be retried
blindly, and a verified result must be bound to the ledger entry).

Default adapter is DenyAllWriteAdapter: no network write occurs until a
Staging-confirmed implementation is composed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from moallem.domain.authorization import (
    PERM_QUIZ_PUBLISH,
    PermissionPolicy,
    authorize,
)
from moallem.domain.errors import ResourceNotFound, TaskStateConflict
from moallem.domain.membership import ActiveContext
from moallem.domain.publishing import PublishIntent, SnapshotDescriptor
from moallem.domain.secrets import SecretVault
from moallem.moodle.client import MoodleClient, MoodleTransport, Token
from moallem.moodle.errors import ConnectionNotActive
from moallem.moodle.service import (
    ConnectionRepository,
    ConnectionStatus,
    MoodleConnection,
)
from moallem.moodle.url_policy import PrivateNetworkProfile, Resolver, normalize_site_url
from moallem.moodle.write import (
    DenyAllWriteAdapter,
    MoodleWriteAdapter,
    QuestionCreateSpec,
    QuizCreateRequest,
    QuizCreateResult,
    QuizVerification,
)


@dataclass(frozen=True, slots=True)
class PublishQuizOutcome:
    create_result: QuizCreateResult
    verification: QuizVerification


class MoodleWriteService:
    """Orchestrates an approved quiz publish to Moodle.

    Order of operations (fail-closed):
    1. Snapshot/connection/tenant binding + PERM_QUIZ_PUBLISH
    2. Connection must be ACTIVE and belong to the active tenant
    3. Reveal token only inside this stack
    4. Delegate create / verify to the injected adapter
    """

    def __init__(
        self,
        *,
        connections: ConnectionRepository,
        vault: SecretVault,
        policy: PermissionPolicy,
        transport: MoodleTransport,
        resolver: Resolver,
        write_adapter: MoodleWriteAdapter | None = None,
        private_profile: PrivateNetworkProfile | None = None,
    ) -> None:
        self._connections = connections
        self._vault = vault
        self._policy = policy
        self._transport = transport
        self._resolver = resolver
        self._write_adapter: MoodleWriteAdapter = write_adapter or DenyAllWriteAdapter()
        self._private = private_profile

    def _client_for(
        self, ctx: ActiveContext, snapshot: SnapshotDescriptor, connection_id: str
    ) -> MoodleClient:
        # Tenant binding comes from the snapshot, not from ctx itself (a tautology).
        if snapshot.tenant_id != ctx.tenant_id:
            raise ResourceNotFound("resource not found")
        if snapshot.connection_id != connection_id:
            raise TaskStateConflict("snapshot connection does not match publish connection")

        conn: MoodleConnection = self._connections.get(ctx, connection_id)
        authorize(ctx, PERM_QUIZ_PUBLISH, conn.tenant_id, self._policy)
        if conn.status is not ConnectionStatus.ACTIVE:
            raise ConnectionNotActive("moodle connection is not active")

        return MoodleClient(
            site=normalize_site_url(conn.site_url),
            token=Token(self._vault.reveal(ctx, conn.secret_ref)),
            transport=self._transport,
            resolver=self._resolver,
            private_profile=self._private,
        )

    def create_approved_quiz(
        self,
        ctx: ActiveContext,
        *,
        connection_id: str,
        snapshot: SnapshotDescriptor,
        intent: PublishIntent,
        questions: Sequence[QuestionCreateSpec],
        quiz_name: str,
        quiz_intro: str = "",
        section_id: int | None = None,
    ) -> QuizCreateResult:
        """Create the quiz (and its questions) in Moodle. Does NOT verify."""
        if not questions:
            raise TaskStateConflict("cannot publish a quiz with zero questions")
        if intent.snapshot_hash != snapshot.snapshot_hash:
            raise TaskStateConflict("publish intent does not match the snapshot")

        client = self._client_for(ctx, snapshot, connection_id)
        request = QuizCreateRequest(
            course_id=snapshot.course_id,
            name=quiz_name,
            intro=quiz_intro,
            external_operation_key=intent.external_operation_key,
            section_id=section_id,
        )
        return self._write_adapter.create_quiz(client, request, questions)

    def verify_created_quiz(
        self,
        ctx: ActiveContext,
        *,
        connection_id: str,
        snapshot: SnapshotDescriptor,
        create_result: QuizCreateResult,
        quiz_name: str,
        expected_question_count: int,
    ) -> QuizVerification:
        """Read the quiz back from Moodle. The create response is never trusted."""
        client = self._client_for(ctx, snapshot, connection_id)
        return self._write_adapter.verify_quiz(
            client,
            course_id=snapshot.course_id,
            moodle_quiz_id=create_result.moodle_quiz_id,
            expected_name=quiz_name,
            expected_question_count=expected_question_count,
        )

    def publish_approved_quiz(
        self,
        ctx: ActiveContext,
        *,
        connection_id: str,
        snapshot: SnapshotDescriptor,
        intent: PublishIntent,
        questions: Sequence[QuestionCreateSpec],
        quiz_name: str,
        quiz_intro: str = "",
        section_id: int | None = None,
    ) -> PublishQuizOutcome:
        """Convenience: create + verify (tests / tools without a ledger)."""
        create_result = self.create_approved_quiz(
            ctx,
            connection_id=connection_id,
            snapshot=snapshot,
            intent=intent,
            questions=questions,
            quiz_name=quiz_name,
            quiz_intro=quiz_intro,
            section_id=section_id,
        )
        verification = self.verify_created_quiz(
            ctx,
            connection_id=connection_id,
            snapshot=snapshot,
            create_result=create_result,
            quiz_name=quiz_name,
            expected_question_count=len(questions),
        )
        return PublishQuizOutcome(create_result=create_result, verification=verification)
