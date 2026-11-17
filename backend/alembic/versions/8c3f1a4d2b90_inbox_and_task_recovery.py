"""add tenant-scoped inbox processing and task recovery lineage

Revision ID: 8c3f1a4d2b90
Revises: 6a1e9dce4f21
Create Date: 2026-11-17 12:28:42.356000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c3f1a4d2b90"
down_revision: str | None = "6a1e9dce4f21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("retry_of_task_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_retry_parent",
        "tasks",
        "tasks",
        ["tenant_id", "retry_of_task_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_tasks_tenant_retry_parent", "tasks", ["tenant_id", "retry_of_task_id"]
    )

    op.add_column("inbox_receipts", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.add_column("inbox_receipts", sa.Column("payload_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "inbox_receipts",
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "inbox_receipts",
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "inbox_receipts",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("inbox_receipts", sa.Column("lease_owner", sa.String(length=128), nullable=True))
    op.add_column(
        "inbox_receipts",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inbox_receipts",
        sa.Column("lease_generation", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "inbox_receipts", sa.Column("last_error_code", sa.String(length=64), nullable=True)
    )

    bind = op.get_bind()
    bind.execute(sa.text("UPDATE inbox_receipts SET state = 'PROCESSED' WHERE state = 'COMPLETED'"))
    invalid_state_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM inbox_receipts "
            "WHERE state NOT IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED')"
        )
    ).scalar_one()
    if invalid_state_count:
        raise RuntimeError(
            f"cannot constrain inbox state: {invalid_state_count} unsupported receipt(s)"
        )

    op.drop_constraint("uq_inbox_consumer_message", "inbox_receipts", type_="unique")
    op.create_unique_constraint(
        "uq_inbox_tenant_consumer_message",
        "inbox_receipts",
        ["tenant_id", "consumer", "message_id"],
    )
    op.create_foreign_key(
        "fk_inbox_receipt_tenant",
        "inbox_receipts",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_inbox_retry_due", "inbox_receipts", ["state", "next_attempt_at"])
    op.create_check_constraint(
        "ck_inbox_receipt_state",
        "inbox_receipts",
        "state IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED')",
    )
    op.create_check_constraint("ck_inbox_receipt_attempts", "inbox_receipts", "attempts >= 0")
    op.create_check_constraint(
        "ck_inbox_lease_generation", "inbox_receipts", "lease_generation >= 0"
    )
    op.create_check_constraint(
        "ck_inbox_receipt_lease",
        "inbox_receipts",
        "(state = 'PROCESSING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
        "OR (state <> 'PROCESSING' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    recovery_task_count = bind.execute(
        sa.text("SELECT count(*) FROM tasks WHERE retry_of_task_id IS NOT NULL")
    ).scalar_one()
    if recovery_task_count:
        raise RuntimeError(
            f"cannot downgrade task recovery lineage: {recovery_task_count} recovery task(s) "
            "would lose their parent reference"
        )
    new_receipt_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM inbox_receipts WHERE tenant_id IS NOT NULL "
            "OR state IN ('PROCESSING', 'FAILED') OR attempts > 0 "
            "OR payload_hash IS NOT NULL OR lease_generation > 0 "
            "OR last_error_code IS NOT NULL"
        )
    ).scalar_one()
    if new_receipt_count:
        raise RuntimeError(
            "cannot downgrade inbox processing data: "
            f"{new_receipt_count} receipt(s) would lose state"
        )

    op.drop_constraint("ck_inbox_receipt_lease", "inbox_receipts", type_="check")
    op.drop_constraint("ck_inbox_lease_generation", "inbox_receipts", type_="check")
    op.drop_constraint("ck_inbox_receipt_attempts", "inbox_receipts", type_="check")
    op.drop_constraint("ck_inbox_receipt_state", "inbox_receipts", type_="check")
    op.drop_index("ix_inbox_retry_due", table_name="inbox_receipts")
    op.drop_constraint("fk_inbox_receipt_tenant", "inbox_receipts", type_="foreignkey")
    op.drop_constraint("uq_inbox_tenant_consumer_message", "inbox_receipts", type_="unique")
    op.create_unique_constraint(
        "uq_inbox_consumer_message", "inbox_receipts", ["consumer", "message_id"]
    )
    bind.execute(sa.text("UPDATE inbox_receipts SET state = 'COMPLETED' WHERE state = 'PROCESSED'"))
    for column in (
        "last_error_code",
        "lease_generation",
        "lease_expires_at",
        "lease_owner",
        "next_attempt_at",
        "retryable",
        "attempts",
        "payload_hash",
        "tenant_id",
    ):
        op.drop_column("inbox_receipts", column)

    op.drop_constraint("uq_tasks_tenant_retry_parent", "tasks", type_="unique")
    op.drop_constraint("fk_tasks_retry_parent", "tasks", type_="foreignkey")
    op.drop_column("tasks", "retry_of_task_id")
