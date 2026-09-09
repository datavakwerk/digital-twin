import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from slowapi.errors import RateLimitExceeded

from .admin import router as admin_router
from .agent.budget import BudgetTracker
from .agent.graph import build_agent
from .chat import router as chat_router
from .config import Settings, get_settings
from .db import (
    InMemoryApprovalStore,
    PostgresApprovalStore,
    create_engine_and_sessions,
    run_migrations,
)
from .knowledge import load_knowledge
from .llm import OpenAICompatProvider
from .rate_limit import limiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver]:
    """Postgres checkpoints when DATABASE_URL is set; otherwise threads live
    only as long as the process (tests, quick bare-metal dev)."""
    if settings.database_url:
        async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
            await saver.setup()  # manages its own tables, outside alembic
            yield saver
    else:
        yield InMemorySaver()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.knowledge = load_knowledge(settings.knowledge_dir)
    logger.info("Loaded %d knowledge documents", len(app.state.knowledge))
    app.state.llm = OpenAICompatProvider(settings, app.state.knowledge)
    app.state.budget = BudgetTracker(settings.daily_budget_usd)
    engine = None
    app.state.sessions = None
    if settings.database_url:
        # Schema to head first, then the async engine and the durable stores.
        await asyncio.to_thread(run_migrations, settings.database_url)
        engine, app.state.sessions = create_engine_and_sessions(settings.database_url)
        app.state.approvals = PostgresApprovalStore(app.state.sessions)
        logger.info("Database ready, schema at head")
    else:
        # No database: nothing survives a restart.
        app.state.approvals = InMemoryApprovalStore()
    async with _checkpointer(settings) as checkpointer:
        # get_provider resolves lazily so tests can swap app.state.llm's client
        # without rebuilding the graph.
        app.state.agent = build_agent(
            lambda: app.state.llm,
            app.state.knowledge,
            checkpointer=checkpointer,
            budget=app.state.budget,
        )
        logger.info(
            "Server ready (checkpoints: %s)", "postgres" if settings.database_url else "in-memory"
        )
        yield
        await app.state.llm.close()
        if engine is not None:
            await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="digital-twin server", lifespan=lifespan)
    app.state.limiter = limiter
    app.include_router(chat_router)
    app.include_router(admin_router)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(_request: Request, _exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit reached — try again in a few minutes."},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_payload(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "Invalid messages payload."})

    @app.get("/api/health")
    async def health(request: Request) -> dict:
        return {
            "ok": True,
            "documents": len(request.app.state.knowledge),
            "database": request.app.state.sessions is not None,
        }

    return app


app = create_app()
