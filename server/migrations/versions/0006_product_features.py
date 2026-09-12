"""Product-feature tables: feedback, unanswered questions, contact archive.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("thread_id", sa.String(64), nullable=False, index=True),
        sa.Column("verdict", sa.String(4), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_table(
        "unanswered_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("thread_id", sa.String(64), nullable=False, index=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(10), nullable=False),
    )
    op.create_table(
        "contact_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("thread_id", sa.String(64), nullable=False, index=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sender_contact", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("contact_messages")
    op.drop_table("unanswered_questions")
    op.drop_table("feedback")
