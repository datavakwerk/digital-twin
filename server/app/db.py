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
import time
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
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


class TurnLogRow(Base):
    """One row per chat turn: tokens, cost, latency, tools, guard outcome."""

    __tablename__ = "turn_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    # "answered" | "refused" | "pending_approval" | "error"
    outcome: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tools_used: Mapped[list[str]] = mapped_column(JSONVariant, default=list)
    guard_flags: Mapped[list[str]] = mapped_column(JSONVariant, default=list)


class BudgetLedgerRow(Base):
    """Daily spend, durable across restarts — backs the hard budget cap."""

    __tablename__ = "budget_ledger"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD (local)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GuardIncidentRow(Base):
    """Refusals and injection attempts with the offending input."""

    __tablename__ = "guard_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    flags: Mapped[list[str]] = mapped_column(JSONVariant)
    visitor_message: Mapped[str] = mapped_column(Text)


class EvalRunRow(Base):
    """One eval-suite invocation: provider, thresholds met, total cost."""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    met: Mapped[bool] = mapped_column(Boolean)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Per-dataset summaries (accuracy, threshold, met) without the case rows.
    summary: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant)
    # {"injected": n, "recovered": n} for --failure-injection runs, else null.
    failure_injection: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)


class EvalCaseRow(Base):
    """One case of one eval run — history instead of overwriting report.json."""

    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    dataset: Mapped[str] = mapped_column(String(40))
    case_id: Mapped[str] = mapped_column(String(80))
    passed: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[Any] = mapped_column(JSONVariant, nullable=True)
    tools: Mapped[list[str]] = mapped_column(JSONVariant, default=list)
    errors: Mapped[list[str]] = mapped_column(JSONVariant, default=list)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


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


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class TurnRecorder:
    """Writes the per-turn telemetry: turn log, budget ledger, guard incidents.

    Best-effort by design — a telemetry failure must never break the visitor's
    chat stream, so every error is logged and swallowed.
    """

    def __init__(self, sessions: async_sessionmaker, provider: str, model: str) -> None:
        self._sessions = sessions
        self._provider = provider
        self._model = model

    async def record(
        self,
        *,
        thread_id: str,
        outcome: str,
        meta: dict[str, Any] | None,
        tools_used: list[str],
        guard_flags: list[str],
        visitor_message: str,
    ) -> None:
        meta = meta or {}
        cost = float(meta.get("costUsd") or 0.0)
        try:
            async with self._sessions() as session:
                session.add(
                    TurnLogRow(
                        thread_id=thread_id,
                        provider=self._provider,
                        model=self._model,
                        outcome=outcome,
                        input_tokens=int(meta.get("inputTokens") or 0),
                        output_tokens=int(meta.get("outputTokens") or 0),
                        cached_tokens=int(meta.get("cachedTokens") or 0),
                        cost_usd=cost,
                        latency_ms=int(meta.get("latencyMs") or 0),
                        tools_used=tools_used,
                        guard_flags=guard_flags,
                    )
                )
                if guard_flags:
                    session.add(
                        GuardIncidentRow(
                            thread_id=thread_id, flags=guard_flags, visitor_message=visitor_message
                        )
                    )
                if cost:
                    await self._add_spend(session, cost)
                await session.commit()
        except Exception:
            logger.exception("Failed to record turn telemetry for thread %s", thread_id)

    async def _add_spend(self, session: Any, cost: float) -> None:
        day = _today()
        result = await session.execute(
            update(BudgetLedgerRow)
            .where(BudgetLedgerRow.day == day)
            .values(spent_usd=BudgetLedgerRow.spent_usd + cost)
        )
        if result.rowcount == 0:
            # First turn of the day; a concurrent insert may win the race.
            try:
                async with session.begin_nested():
                    session.add(BudgetLedgerRow(day=day, spent_usd=cost))
            except IntegrityError:
                await session.execute(
                    update(BudgetLedgerRow)
                    .where(BudgetLedgerRow.day == day)
                    .values(spent_usd=BudgetLedgerRow.spent_usd + cost)
                )


async def load_today_spent(sessions: async_sessionmaker) -> float:
    """Seed the in-memory budget tracker after a restart (restart-proof cap)."""
    async with sessions() as session:
        spent = await session.scalar(
            select(BudgetLedgerRow.spent_usd).where(BudgetLedgerRow.day == _today())
        )
    return float(spent or 0.0)


async def record_eval_run(sessions: async_sessionmaker, report: dict[str, Any]) -> int:
    """Persist one eval-suite report: an eval_runs row plus one eval_cases row
    per case. Returns the run id. Raises on failure — an eval run whose
    history can't be written should fail loudly, unlike chat telemetry."""
    datasets = report.get("datasets") or []
    run = EvalRunRow(
        provider=report["provider"],
        model=report["model"],
        met=all(summary["met"] for summary in datasets) if datasets else False,
        cost_usd=round(sum(summary.get("costUsd") or 0.0 for summary in datasets), 5),
        summary=[
            {key: value for key, value in summary.items() if key != "results"}
            for summary in datasets
        ],
        failure_injection=report.get("failure_injection"),
    )
    async with sessions() as session:
        session.add(run)
        await session.flush()  # assigns run.id for the case rows
        for summary in datasets:
            for row in summary.get("results") or []:
                session.add(
                    EvalCaseRow(
                        run_id=run.id,
                        dataset=summary["dataset"],
                        case_id=row["id"],
                        passed=row["passed"],
                        detail=row.get("detail"),
                        tools=row.get("tools") or [],
                        errors=row.get("errors") or [],
                        cost_usd=row.get("costUsd") or 0.0,
                        latency_ms=row.get("latencyMs") or 0,
                    )
                )
        await session.commit()
    return run.id
