"""Eval history: one row per run (eval_runs) and per case (eval_cases).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("met", sa.Boolean(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("summary", _json(), nullable=False),
        sa.Column("failure_injection", _json(), nullable=True),
    )
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("dataset", sa.String(40), nullable=False),
        sa.Column("case_id", sa.String(80), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("detail", _json(), nullable=True),
        sa.Column("tools", _json(), nullable=False),
        sa.Column("errors", _json(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("eval_cases")
    op.drop_table("eval_runs")
