import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .config import get_settings
from .knowledge import load_knowledge
from .chat import router as chat_router
from .llm import OpenAICompatProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.knowledge = load_knowledge(settings.knowledge_dir)
    logger.info("Loaded %d knowledge documents", len(app.state.knowledge))
    app.state.llm = OpenAICompatProvider(settings, app.state.knowledge)
    yield
    await app.state.llm.close()

def create_app() -> FastAPI:
    app = FastAPI(title="digital-twin server", lifespan=lifespan)
    app.include_router(chat_router)

    @app.get("/api/health")
    async def health(request: Request) -> dict:
        return {"ok": True, "documents": len(request.app.state.knowledge)}

    return app


app = create_app()
