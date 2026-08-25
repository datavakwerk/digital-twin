import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from .chat import router as chat_router
from .config import get_settings
from .knowledge import load_knowledge
from .llm import OpenAICompatProvider
from .rate_limit import limiter

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
    app.state.limiter = limiter
    app.include_router(chat_router)

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
        return {"ok": True, "documents": len(request.app.state.knowledge)}

    return app


app = create_app()
