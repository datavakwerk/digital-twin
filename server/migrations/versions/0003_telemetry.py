"""Telemetry: turn log, budget ledger, guard incidents.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(JSONB(), "postgresql")


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "turn_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("thread_id", sa.String(64), nullable=False, index=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tools_used", _json(), nullable=False),
        sa.Column("guard_flags", _json(), nullable=False),
    )
    op.create_table(
        "budget_ledger",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("spent_usd", sa.Float(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "guard_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("thread_id", sa.String(64), nullable=False, index=True),
        sa.Column("flags", _json(), nullable=False),
        sa.Column("visitor_message", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("guard_incidents")
    op.drop_table("budget_ledger")
    op.drop_table("turn_log")
