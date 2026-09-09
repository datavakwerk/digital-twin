"""Enable the pgvector extension.

The first migration holds no tables — it proves the migration path end to
end and prepares the vector support that Commit 25 builds on. Harmless
until then.

Revision ID: 0001
Revises:
Create Date: 2026-09-06
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres only — the unit tests run these migrations against SQLite.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    pass
