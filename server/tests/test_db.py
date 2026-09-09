"""Data platform units — run against SQLite so no Postgres is needed; the
dialect-specific bits (JSONB, later pgvector) are variants that only
activate on Postgres."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import (
    Base,
    InMemoryApprovalStore,
    PostgresApprovalStore,
    run_migrations,
    sqlalchemy_url,
)
from app.main import create_app


@pytest.fixture
def sessions():
    engine = create_async_engine("sqlite+aiosqlite://")

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


def test_sqlalchemy_url_pins_psycopg_driver():
    assert sqlalchemy_url("postgresql://u:p@db:5432/twin").startswith("postgresql+psycopg://")
    assert sqlalchemy_url("sqlite:///x.db") == "sqlite:///x.db"


def test_migrations_run_to_head(tmp_path):
    url = f"sqlite:///{tmp_path}/migrated.db"
    run_migrations(url)
    run_migrations(url)  # idempotent: a second start finds nothing to do

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {"alembic_version", "pending_approvals"} <= tables
    engine.dispose()


def test_health_reports_no_database_by_default():
    with TestClient(create_app()) as client:
        body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["database"] is False


def test_in_memory_approval_store_round_trip():
    async def run():
        store = InMemoryApprovalStore()
        await store.add("t-1", {"visitor_message": "hire Ruud"})
        assert await store.list() == [{"thread_id": "t-1", "visitor_message": "hire Ruud"}]
        await store.remove("t-1")
        assert await store.list() == []

    asyncio.run(run())


def test_postgres_approval_store_round_trip(sessions):
    async def run():
        store = PostgresApprovalStore(sessions)
        await store.add("t-1", {"visitor_message": "hire Ruud", "tool_calls": []})
        await store.add("t-1", {"visitor_message": "updated"})  # upsert, not duplicate
        assert await store.get("t-1") == {"thread_id": "t-1", "visitor_message": "updated"}
        assert await store.list() == [{"thread_id": "t-1", "visitor_message": "updated"}]
        await store.remove("t-1")
        assert await store.list() == []

    asyncio.run(run())
