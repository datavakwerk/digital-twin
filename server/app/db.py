"""Data platform: Postgres persistence behind small interfaces.

Postgres is the database of record. With DATABASE_URL unset (tests, quick
bare-metal dev) the app runs on in-memory fallbacks and nothing survives a
restart.

Privacy invariant: no table stores IPs or fingerprints — rows are keyed by
the anonymous thread_id only, and rate limiting stays in-memory.

Schema changes go through alembic (server/migrations/); `run_migrations` is
called at startup so a deploy is always at head.
"""

import logging
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import JSON, DateTime, String, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)

SERVER_DIR = Path(__file__).resolve().parent.parent

# JSONB on Postgres, plain JSON elsewhere (tests run the models on SQLite).
JSONVariant = JSON().with_variant(JSONB(), "postgresql")

def sqlalchemy_url(database_url: str) -> str:
    """Pin the psycopg3 driver onto a plain postgresql:// URL."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Base(DeclarativeBase):
    pass

class PendingApprovalRow(Base):
    """High-risk actions awaiting Ruud's decision — survives restarts."""

    __tablename__ = "pending_approvals"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())

def create_engine_and_sessions(database_url: str) -> tuple[AsyncEngine, async_sessionmaker]:
    engine = create_async_engine(sqlalchemy_url(database_url), pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def run_migrations(database_url: str) -> None:
    """Bring the schema to head. Sync (alembic is sync) — call via to_thread."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url(database_url))
    command.upgrade(cfg, "head")

class ApprovalStore(Protocol):
    async def add(self, thread_id: str, payload: dict[str, Any]) -> None: ...
    async def get(self, thread_id: str) -> dict[str, Any] | None: ...
    async def list(self) -> list[dict[str, Any]]: ...
    async def remove(self, thread_id: str) -> None: ...


class InMemoryApprovalStore:
    """Fallback without a database; the checkpoints stay the source of truth."""

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}

    async def add(self, thread_id: str, payload: dict[str, Any]) -> None:
        self._pending[thread_id] = {"thread_id": thread_id, **payload}

    async def get(self, thread_id: str) -> dict[str, Any] | None:
        return self._pending.get(thread_id)

    async def list(self) -> list[dict[str, Any]]:
        return list(self._pending.values())

    async def remove(self, thread_id: str) -> None:
        self._pending.pop(thread_id, None)


class PostgresApprovalStore:
    def __init__(self, sessions: async_sessionmaker) -> None:
        self._sessions = sessions

    async def add(self, thread_id: str, payload: dict[str, Any]) -> None:
        async with self._sessions() as session:
            await session.merge(PendingApprovalRow(thread_id=thread_id, payload=payload))
            await session.commit()

    async def get(self, thread_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            row = await session.get(PendingApprovalRow, thread_id)
        return None if row is None else {"thread_id": row.thread_id, **row.payload}

    async def list(self) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            query = select(PendingApprovalRow).order_by(PendingApprovalRow.created_at)
            rows = (await session.execute(query)).scalars().all()
        return [{"thread_id": row.thread_id, **row.payload} for row in rows]

    async def remove(self, thread_id: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                delete(PendingApprovalRow).where(PendingApprovalRow.thread_id == thread_id)
            )
            await session.commit()
