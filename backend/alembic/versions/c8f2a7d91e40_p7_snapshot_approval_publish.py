"""add immutable quiz snapshots, approvals and durable external publish ledger

Revision ID: c8f2a7d91e40
Revises: f4a2d9c61b80
Create Date: 2026-11-17 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8f2a7d91e40"
down_revision: str | None = "f4a2d9c61b80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("result_payload", postgresql.JSONB(), nullable=True))
    op.create_table(
        "quiz_draft_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(128), nullable=False),
        sa.Column("destination", postgresql.JSONB(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("quality_report", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_quiz_draft_snapshots_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "task_id", "version_no", name="uq_quiz_draft_snapshots_version"
        ),
        sa.UniqueConstraint(
            "tenant_id", "task_id", "snapshot_hash", name="uq_quiz_draft_snapshots_hash"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_quiz_draft_snapshots_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_quiz_draft_snapshots_membership",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version_no >= 1", name="ck_quiz_draft_snapshots_version"),
        sa.CheckConstraint(
            "snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_quiz_draft_snapshots_hash"
        ),
    )
    op.create_index(
        "ix_quiz_draft_snapshots_task_version",
        "quiz_draft_snapshots",
        ["tenant_id", "task_id", "version_no"],
    )

    op.create_table(
        "quiz_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("approver_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("comment", sa.String(2000)),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_quiz_approvals_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "task_id", "snapshot_id", "approver_membership_id",
            name="uq_quiz_approvals_actor_snapshot",
        ),
        sa.UniqueConstraint(
            "tenant_id", "approver_membership_id", "idempotency_key_hash",
            name="uq_quiz_approvals_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"], ["tasks.tenant_id", "tasks.id"],
            name="fk_quiz_approvals_task", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["quiz_draft_snapshots.tenant_id", "quiz_draft_snapshots.id"],
            name="fk_quiz_approvals_snapshot", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approver_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_quiz_approvals_membership", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("decision IN ('APPROVED', 'REJECTED')", name="ck_quiz_approvals_decision"),
        sa.CheckConstraint(
            "snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_quiz_approvals_snapshot_hash"
        ),
        sa.CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$'", name="ck_quiz_approvals_idempotency_hash"
        ),
        sa.CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_quiz_approvals_request_hash"),
        sa.CheckConstraint("expires_at > decided_at", name="ck_quiz_approvals_expiry"),
    )

    op.create_table(
        "publish_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("external_operation_key", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), server_default="PREPARED", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_publish_intents_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "task_id", "snapshot_id", name="uq_publish_intents_task_snapshot"
        ),
        sa.UniqueConstraint(
            "tenant_id", "external_operation_key", name="uq_publish_intents_operation_key"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"], ["tasks.tenant_id", "tasks.id"],
            name="fk_publish_intents_task", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["quiz_draft_snapshots.tenant_id", "quiz_draft_snapshots.id"],
            name="fk_publish_intents_snapshot", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["quiz_approvals.tenant_id", "quiz_approvals.id"],
            name="fk_publish_intents_approval", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "state IN ('PREPARED', 'EXECUTING', 'VERIFYING', 'COMPLETED', "
            "'NEEDS_RECONCILIATION', 'FAILED', 'MANUAL_REVIEW')",
            name="ck_publish_intents_state",
        ),
        sa.CheckConstraint(
            "snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_publish_intents_snapshot_hash"
        ),
        sa.CheckConstraint(
            "external_operation_key ~ '^[0-9a-f]{64}$'", name="ck_publish_intents_operation_key"
        ),
    )
    op.create_index(
        "ix_publish_intents_state_created", "publish_intents", ["state", "created_at"]
    )

    op.create_table(
        "tool_invocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publish_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_step_key", sa.String(64), nullable=False),
        sa.Column("step_kind", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), server_default="0", nullable=False),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("response_hash", sa.String(64)),
        sa.Column("state", sa.String(32), server_default="PLANNED", nullable=False),
        sa.Column("external_ref", sa.String(512)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "publish_intent_id", "external_step_key",
            name="uq_tool_invocations_step_key",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "publish_intent_id"],
            ["publish_intents.tenant_id", "publish_intents.id"],
            name="fk_tool_invocations_publish_intent", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_tool_invocations_ordinal"),
        sa.CheckConstraint("attempt_no >= 0", name="ck_tool_invocations_attempt"),
        sa.CheckConstraint(
            "state IN ('PLANNED', 'DISPATCHED', 'SUCCEEDED', 'FAILED_DEFINITE', 'UNKNOWN', "
            "'RECONCILED_PRESENT', 'RECONCILED_ABSENT', 'MANUAL_REVIEW')",
            name="ck_tool_invocations_state",
        ),
        sa.CheckConstraint(
            "external_step_key ~ '^[0-9a-f]{64}$'", name="ck_tool_invocations_step_key"
        ),
        sa.CheckConstraint(
            "request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_tool_invocations_request_hash",
        ),
        sa.CheckConstraint(
            "response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'",
            name="ck_tool_invocations_response_hash",
        ),
    )
    op.create_index(
        "ix_tool_invocations_intent_state", "tool_invocations",
        ["tenant_id", "publish_intent_id", "state"],
    )

    # Snapshot and approval rows are append-only. New draft content creates a new version; an
    # approval is never edited or transferred to a newer hash.
    op.execute(
        """CREATE FUNCTION moallem_reject_immutable_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'immutable audit record cannot be changed';
        END;
        $$ LANGUAGE plpgsql"""
    )
    for table in ("quiz_draft_snapshots", "quiz_approvals"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION moallem_reject_immutable_mutation()"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_quiz_approvals_immutable ON quiz_approvals")
    op.execute("DROP TRIGGER IF EXISTS trg_quiz_draft_snapshots_immutable ON quiz_draft_snapshots")
    op.execute("DROP FUNCTION IF EXISTS moallem_reject_immutable_mutation()")
    op.drop_index("ix_tool_invocations_intent_state", table_name="tool_invocations")
    op.drop_table("tool_invocations")
    op.drop_index("ix_publish_intents_state_created", table_name="publish_intents")
    op.drop_table("publish_intents")
    op.drop_table("quiz_approvals")
    op.drop_index("ix_quiz_draft_snapshots_task_version", table_name="quiz_draft_snapshots")
    op.drop_table("quiz_draft_snapshots")
    op.drop_column("tasks", "result_payload")
