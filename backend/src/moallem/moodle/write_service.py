"""Moodle write orchestration (Phase B).

Performs the same fail-closed checks as MoodleReadService, then delegates the
actual side effect to an injected MoodleWriteAdapter.

Default adapter is DenyAllWriteAdapter — no network write occurs until a
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
    1. Tenant isolation + PERM_QUIZ_PUBLISH
    2. Connection must be ACTIVE
    3. Reveal token only inside this stack
    4. Delegate create + verify to the injected adapter
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

    def _get_active_connection(
        self, ctx: ActiveContext, connection_id: str
    ) -> MoodleConnection:
        conn = self._connections.get(ctx, connection_id)
        if conn.status is not ConnectionStatus.ACTIVE:
            raise ConnectionNotActive("moodle connection is not active")
        return conn

    def _client_for(self, ctx: ActiveContext, connection_id: str) -> tuple[MoodleClient, MoodleConnection]:
        # Permission first (same pattern as read service)
        authorize(ctx, PERM_QUIZ_PUBLISH, ctx.tenant_id, self._policy)

        conn = self._get_active_connection(ctx, connection_id)
        # Destination must match the snapshot's connection in the real worker;
        # here we only enforce the live connection state.
        site = normalize_site_url(conn.site_url)
        raw = self._vault.reveal(conn.secret_ref)
        token = Token(raw)
        client = MoodleClient(
            transport=self._transport,
            resolver=self._resolver,
            site_url=site,
            token=token,
            private_profile=self._private,
        )
        return client, conn

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
        """Create the quiz in Moodle and verify it.

        Caller (worker) is responsible for:
        - ensuring PublishPreflight is ready
        - ensuring approval is valid for this snapshot
        - ledger transitions based on the returned outcome
        """
        if snapshot.tenant_id != ctx.tenant_id:
            # Defence in depth; authorize() also checks tenant on the action
            from moallem.domain.errors import ResourceNotFound

            raise ResourceNotFound("resource not found")

        if snapshot.connection_id != connection_id:
            from moallem.domain.errors import TaskStateConflict

            raise TaskStateConflict("snapshot connection does not match publish connection")

        if not questions:
            from moallem.domain.errors import TaskStateConflict

            raise TaskStateConflict("cannot publish a quiz with zero questions")

        client, _conn = self._client_for(ctx, connection_id)

        request = QuizCreateRequest(
            course_id=snapshot.course_id,
            name=quiz_name,
            intro=quiz_intro,
            external_operation_key=intent.external_operation_key,
            section_id=section_id,
        )

        create_result = self._write_adapter.create_quiz(client, request, questions)

        verification = self._write_adapter.verify_quiz(
            client,
            course_id=snapshot.course_id,
            moodle_quiz_id=create_result.moodle_quiz_id,
            expected_name=quiz_name,
            expected_question_count=len(questions),
        )

        return PublishQuizOutcome(create_result=create_result, verification=verification)
