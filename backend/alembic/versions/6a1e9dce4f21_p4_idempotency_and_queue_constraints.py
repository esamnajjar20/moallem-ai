"""constrain idempotency references and index leased outbox recovery

Revision ID: 6a1e9dce4f21
Revises: 37cc62a430a9
Create Date: 2026-11-20 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "6a1e9dce4f21"
down_revision: str | None = "37cc62a430a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    orphan_count = connection.execute(
        text(
            "SELECT count(*) FROM idempotency_records AS i "
            "LEFT JOIN tasks AS t ON t.tenant_id = i.tenant_id AND t.id = i.operation_ref "
            "WHERE t.id IS NULL"
        )
    ).scalar_one()
    if orphan_count:
        raise RuntimeError(
            f"cannot add idempotency task foreign key: {orphan_count} orphan record(s)"
        )

    op.create_foreign_key(
        "fk_idempotency_operation_task",
        "idempotency_records",
        "tasks",
        ["tenant_id", "operation_ref"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "ix_idempotency_operation",
        "idempotency_records",
        ["tenant_id", "operation_ref"],
    )
    op.create_check_constraint(
        "ck_idempotency_state",
        "idempotency_records",
        "state IN ('IN_PROGRESS', 'COMPLETED', 'FAILED_FINAL')",
    )
    op.create_index(
        "ix_outbox_lease_expiry",
        "outbox_events",
        ["lease_expires_at"],
        postgresql_where=text("status = 'LEASED'"),
    )
    op.create_check_constraint(
        "ck_outbox_status",
        "outbox_events",
        "status IN ('PENDING', 'LEASED', 'PUBLISHED', 'DEAD_LETTER')",
    )
    op.create_check_constraint("ck_outbox_attempts", "outbox_events", "attempts >= 0")
    op.create_check_constraint(
        "ck_outbox_lease_generation", "outbox_events", "lease_generation >= 0"
    )
    op.create_check_constraint(
        "ck_outbox_lease",
        "outbox_events",
        "(status = 'LEASED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
        "OR (status <> 'LEASED' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_outbox_lease", "outbox_events", type_="check")
    op.drop_constraint("ck_outbox_lease_generation", "outbox_events", type_="check")
    op.drop_constraint("ck_outbox_attempts", "outbox_events", type_="check")
    op.drop_constraint("ck_outbox_status", "outbox_events", type_="check")
    op.drop_index("ix_outbox_lease_expiry", table_name="outbox_events")
    op.drop_constraint("ck_idempotency_state", "idempotency_records", type_="check")
    op.drop_index("ix_idempotency_operation", table_name="idempotency_records")
    op.drop_constraint("fk_idempotency_operation_task", "idempotency_records", type_="foreignkey")
