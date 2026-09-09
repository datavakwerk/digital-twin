"""Data platform units — run against SQLite so no Postgres is needed; the
dialect-specific bits only activate on Postgres."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.db import run_migrations, sqlalchemy_url
from app.main import create_app


def test_sqlalchemy_url_pins_psycopg_driver():
    assert sqlalchemy_url("postgresql://u:p@db:5432/twin").startswith("postgresql+psycopg://")
    assert sqlalchemy_url("sqlite:///x.db") == "sqlite:///x.db"


def test_migrations_run_to_head(tmp_path):
    url = f"sqlite:///{tmp_path}/migrated.db"
    run_migrations(url)
    run_migrations(url)  # idempotent: a second start finds nothing to do

    engine = create_engine(url)
    assert "alembic_version" in inspect(engine).get_table_names()
    engine.dispose()


def test_health_reports_no_database_by_default():
    with TestClient(create_app()) as client:
        body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["database"] is False
