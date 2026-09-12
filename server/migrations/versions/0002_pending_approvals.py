"""Approval queue: high-risk actions awaiting Ruud's decision.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "pending_approvals",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("payload", _json(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("pending_approvals")
