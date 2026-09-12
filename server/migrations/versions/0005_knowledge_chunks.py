"""Knowledge chunks with pgvector embeddings for semantic search.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    embedding = sa.JSON().with_variant(Vector(), "postgresql")
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_slug", sa.String(80), nullable=False, index=True),
        sa.Column("doc_title", sa.String(200), nullable=False),
        sa.Column("heading", sa.String(200), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        sa.Column("embedding", embedding, nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False, index=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # The corpus is small (dozens of chunks): an exact scan is fine, no ANN
    # index. Add an HNSW index here once the corpus grows into the thousands.


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
