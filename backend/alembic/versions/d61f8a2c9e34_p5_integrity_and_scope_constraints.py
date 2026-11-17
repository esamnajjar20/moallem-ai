"""tighten P5 hashes, storage references, and course scope types

Revision ID: d61f8a2c9e34
Revises: b51a7c2d9e30
Create Date: 2026-11-17 16:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d61f8a2c9e34"
down_revision: str | None = "b51a7c2d9e30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_course_scope_dependencies() -> None:
    op.drop_constraint(
        "fk_ai_usage_source_refs_chunk_course", "ai_usage_source_refs", type_="foreignkey"
    )
    op.drop_constraint("uq_source_chunks_tenant_course", "source_chunks", type_="unique")
    op.drop_constraint(
        "fk_source_chunks_file_provenance", "source_chunks", type_="foreignkey"
    )
    op.drop_index("ix_source_chunks_tenant_course_file", table_name="source_chunks")


def _create_course_scope_dependencies() -> None:
    op.create_unique_constraint(
        "uq_source_chunks_tenant_course",
        "source_chunks",
        ["tenant_id", "id", "course_id"],
    )
    op.create_index(
        "ix_source_chunks_tenant_course_file",
        "source_chunks",
        ["tenant_id", "course_id", "file_id"],
    )
    op.create_foreign_key(
        "fk_source_chunks_file_provenance",
        "source_chunks",
        "source_files",
        ["tenant_id", "file_id", "file_version", "course_id"],
        ["tenant_id", "id", "version", "course_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_ai_usage_source_refs_chunk_course",
        "ai_usage_source_refs",
        "source_chunks",
        ["tenant_id", "source_chunk_id", "course_id"],
        ["tenant_id", "id", "course_id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    # Course IDs are bounded to 128 characters at task and source-file boundaries.
    _drop_course_scope_dependencies()
    op.alter_column(
        "source_chunks",
        "course_id",
        existing_type=sa.String(length=255),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    _create_course_scope_dependencies()

    op.create_check_constraint(
        "ck_ai_usage_request_hash_hex",
        "ai_usage_ledger",
        "request_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_ai_usage_response_hash_hex",
        "ai_usage_ledger",
        "response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_source_files_sha256_hex",
        "source_files",
        "sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_source_files_private_storage_ref",
        "source_files",
        "length(storage_ref) > 0 AND storage_ref = btrim(storage_ref) "
        "AND storage_ref !~ '[[:space:]]' AND storage_ref !~ '[[:cntrl:]]' "
        "AND storage_ref !~ '[?#]' AND storage_ref !~ '^//' "
        "AND (storage_ref !~* '^[a-z][a-z0-9+.-]*:' "
        "OR storage_ref ~* '^(s3|gs|gcs|az|azure|r2)://[^/@?#]+(/[^?#]*)?$')",
    )
    op.create_check_constraint(
        "ck_source_chunks_content_hash_hex",
        "source_chunks",
        "content_hash ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_source_chunks_content_hash_hex", "source_chunks", type_="check"
    )
    op.drop_constraint(
        "ck_source_files_private_storage_ref", "source_files", type_="check"
    )
    op.drop_constraint("ck_source_files_sha256_hex", "source_files", type_="check")
    op.drop_constraint(
        "ck_ai_usage_response_hash_hex", "ai_usage_ledger", type_="check"
    )
    op.drop_constraint(
        "ck_ai_usage_request_hash_hex", "ai_usage_ledger", type_="check"
    )

    _drop_course_scope_dependencies()
    op.alter_column(
        "source_chunks",
        "course_id",
        existing_type=sa.String(length=128),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    _create_course_scope_dependencies()
