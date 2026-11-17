"""index legacy unscoped Inbox receipts used as fail-closed deduplication tombstones

Revision ID: 9d4e7a2c1b60
Revises: 8c3f1a4d2b90
Create Date: 2026-11-17 15:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d4e7a2c1b60"
down_revision: str | None = "8c3f1a4d2b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Also protect databases that had already applied 8c before the migration was
    # corrected: legacy PROCESSING receipts have no attributable tenant or fencing
    # token, so they must be preserved but never replayed automatically.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE inbox_receipts "
            "SET state = 'FAILED', retryable = false, "
            "last_error_code = 'LEGACY_PROCESSING_OUTCOME_UNKNOWN', "
            "completed_at = COALESCE(completed_at, now()), "
            "lease_owner = NULL, lease_expires_at = NULL "
            "WHERE tenant_id IS NULL AND state = 'PROCESSING'"
        )
    )
    op.create_index(
        "uq_inbox_legacy_unscoped_dedup",
        "inbox_receipts",
        ["consumer", "message_id"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_inbox_legacy_unscoped_dedup", table_name="inbox_receipts")
