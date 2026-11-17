"""add account lifecycle state for immediate API-side suspension

Revision ID: f4a2d9c61b80
Revises: d61f8a2c9e34
Create Date: 2026-11-17 20:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a2d9c61b80"
down_revision: str | None = "d61f8a2c9e34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_status", sa.String(length=16), server_default="ACTIVE", nullable=False),
    )
    op.create_check_constraint(
        "ck_users_auth_status",
        "users",
        "auth_status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_auth_status", "users", type_="check")
    op.drop_column("users", "auth_status")
