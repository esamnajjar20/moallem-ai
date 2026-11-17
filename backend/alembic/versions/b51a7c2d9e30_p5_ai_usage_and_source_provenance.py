"""add provider usage ledger and tenant-scoped source provenance for P5

Revision ID: b51a7c2d9e30
Revises: 9d4e7a2c1b60
Create Date: 2026-11-17 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b51a7c2d9e30"
down_revision: str | None = "9d4e7a2c1b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_tasks_tenant_id_course", "tasks", ["tenant_id", "id", "course_id"]
    )
    op.create_table(
        "ai_usage_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.String(length=128), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("pricing_version", sa.String(length=128), nullable=False),
        sa.Column("permit_ref", sa.String(length=128), nullable=False),
        sa.Column("privacy_policy_ref", sa.String(length=128), nullable=False),
        sa.Column("budget_reservation_ref", sa.String(length=128), nullable=False),
        sa.Column("budget_reserved_amount", sa.Numeric(precision=24, scale=12), nullable=False),
        sa.Column("budget_currency", sa.String(length=3), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "state", sa.String(length=16), server_default="STARTED", nullable=False
        ),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(precision=24, scale=12), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('STARTED', 'SUCCEEDED', 'FAILED', 'UNKNOWN')",
            name="ck_ai_usage_state",
        ),
        sa.CheckConstraint("octet_length(request_hash) = 64", name="ck_ai_usage_request_hash"),
        sa.CheckConstraint(
            "response_hash IS NULL OR octet_length(response_hash) = 64",
            name="ck_ai_usage_response_hash",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_usage_input_tokens"
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_usage_output_tokens"
        ),
        sa.CheckConstraint("cost_amount IS NULL OR cost_amount >= 0", name="ck_ai_usage_cost"),
        sa.CheckConstraint("budget_reserved_amount > 0", name="ck_ai_usage_budget_reserved"),
        sa.CheckConstraint("budget_currency ~ '^[A-Z]{3}$'", name="ck_ai_usage_budget_currency"),
        sa.CheckConstraint(
            "(cost_amount IS NULL AND currency IS NULL) OR "
            "(cost_amount IS NOT NULL AND currency ~ '^[A-Z]{3}$')",
            name="ck_ai_usage_currency",
        ),
        sa.CheckConstraint(
            "(state = 'STARTED' AND finished_at IS NULL) OR "
            "(state <> 'STARTED' AND finished_at IS NOT NULL)",
            name="ck_ai_usage_finished_state",
        ),
        sa.CheckConstraint(
            "state <> 'SUCCEEDED' OR "
            "(input_tokens IS NOT NULL AND output_tokens IS NOT NULL "
            "AND cost_amount IS NOT NULL AND currency IS NOT NULL "
            "AND response_hash IS NOT NULL)",
            name="ck_ai_usage_success_complete",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id", "course_id"],
            ["tasks.tenant_id", "tasks.id", "tasks.course_id"],
            name="fk_ai_usage_task_course",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_ai_usage_actor_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "task_id", "invocation_id", name="uq_ai_usage_task_invocation"
        ),
    )
    op.create_index(
        "ix_ai_usage_tenant_started", "ai_usage_ledger", ["tenant_id", "started_at"]
    )
    op.create_index(
        "ix_ai_usage_tenant_task", "ai_usage_ledger", ["tenant_id", "task_id"]
    )

    op.create_table(
        "source_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("uploaded_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("declared_mime_type", sa.String(length=128), nullable=False),
        sa.Column("detected_mime_type", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_ref", sa.String(length=512), nullable=False),
        sa.Column("extraction_profile", sa.String(length=32), nullable=False),
        sa.Column(
            "state", sa.String(length=16), server_default="QUARANTINED", nullable=False
        ),
        sa.Column("scanner_id", sa.String(length=128), nullable=True),
        sa.Column("scanner_version", sa.String(length=128), nullable=True),
        sa.Column("scan_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extractor_version", sa.String(length=128), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_source_files_version"),
        sa.CheckConstraint("byte_size > 0", name="ck_source_files_byte_size"),
        sa.CheckConstraint("octet_length(sha256) = 64", name="ck_source_files_sha256"),
        sa.CheckConstraint(
            "state IN ('QUARANTINED', 'CLEAN', 'REJECTED', 'EXTRACTED', 'FAILED')",
            name="ck_source_files_state",
        ),
        sa.CheckConstraint("page_count IS NULL OR page_count >= 0", name="ck_source_files_pages"),
        sa.CheckConstraint("chunk_count >= 0", name="ck_source_files_chunks"),
        sa.CheckConstraint(
            "state <> 'EXTRACTED' OR (extractor_version IS NOT NULL AND chunk_count > 0)",
            name="ck_source_files_extracted_complete",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_source_files_uploader_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id", "course_id"],
            ["tasks.tenant_id", "tasks.id", "tasks.course_id"],
            name="fk_source_files_task_course",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_source_files_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "version",
            "course_id",
            name="uq_source_files_provenance_scope",
        ),
    )
    op.create_index(
        "ix_source_files_tenant_course_state",
        "source_files",
        ["tenant_id", "course_id", "state"],
    )
    op.create_index(
        "ix_source_files_tenant_hash", "source_files", ["tenant_id", "sha256"]
    )

    op.create_table(
        "source_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.String(length=255), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("file_version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_path", sa.String(length=1024), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("chunk_index >= 0", name="ck_source_chunks_index"),
        sa.CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_source_chunks_page"),
        sa.CheckConstraint("length(content) > 0", name="ck_source_chunks_content"),
        sa.CheckConstraint("octet_length(content_hash) = 64", name="ck_source_chunks_hash"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_id", "file_version", "course_id"],
            [
                "source_files.tenant_id",
                "source_files.id",
                "source_files.version",
                "source_files.course_id",
            ],
            name="fk_source_chunks_file_provenance",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "file_id", "file_version", "chunk_index", name="uq_source_chunk_order"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_source_chunks_tenant_id"),
        sa.UniqueConstraint("tenant_id", "id", "course_id", name="uq_source_chunks_tenant_course"),
    )
    op.create_index(
        "ix_source_chunks_tenant_course_file",
        "source_chunks",
        ["tenant_id", "course_id", "file_id"],
    )

    op.create_table(
        "ai_usage_source_refs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.String(length=128), nullable=False),
        sa.Column("source_chunk_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id", "invocation_id"],
            [
                "ai_usage_ledger.tenant_id",
                "ai_usage_ledger.task_id",
                "ai_usage_ledger.invocation_id",
            ],
            name="fk_ai_usage_source_refs_usage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id", "course_id"],
            ["tasks.tenant_id", "tasks.id", "tasks.course_id"],
            name="fk_ai_usage_source_refs_task_course",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_chunk_id", "course_id"],
            ["source_chunks.tenant_id", "source_chunks.id", "source_chunks.course_id"],
            name="fk_ai_usage_source_refs_chunk_course",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "task_id", "invocation_id", "source_chunk_id"
        ),
    )
    op.create_index(
        "ix_ai_usage_source_refs_source",
        "ai_usage_source_refs",
        ["tenant_id", "source_chunk_id"],
    )


def downgrade() -> None:
    # Preserve the no-data-loss downgrade guard in offline SQL generation as well.
    for table in ("ai_usage_source_refs", "source_chunks", "source_files", "ai_usage_ledger"):
        # Table names are an internal constant allow-list above, never user-controlled.
        op.execute(
            f"""
            DO $moallem$ DECLARE row_count bigint;
            BEGIN
                SELECT count(*) INTO row_count FROM {table};
                IF row_count > 0 THEN
                    RAISE EXCEPTION 'cannot downgrade P5 schema: % row(s) would be lost from {table}',
                        row_count USING ERRCODE = '23514';
                END IF;
            END $moallem$;
            """
        )

    op.drop_index("ix_ai_usage_source_refs_source", table_name="ai_usage_source_refs")
    op.drop_table("ai_usage_source_refs")
    op.drop_index("ix_source_chunks_tenant_course_file", table_name="source_chunks")
    op.drop_table("source_chunks")
    op.drop_index("ix_source_files_tenant_hash", table_name="source_files")
    op.drop_index("ix_source_files_tenant_course_state", table_name="source_files")
    op.drop_table("source_files")
    op.drop_index("ix_ai_usage_tenant_task", table_name="ai_usage_ledger")
    op.drop_index("ix_ai_usage_tenant_started", table_name="ai_usage_ledger")
    op.drop_table("ai_usage_ledger")
    op.drop_constraint("uq_tasks_tenant_id_course", "tasks", type_="unique")
