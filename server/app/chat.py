import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .config import get_settings
from .rate_limit import limiter
from .schemas import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/chat")
@limiter.limit(get_settings().rate_limit)
async def chat(request: Request, payload: ChatRequest) -> StreamingResponse:
    turns = [{"role": t.role, "content": t.content} for t in payload.messages]
    return StreamingResponse(
        stream_sse(request.app.state.llm, turns),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def stream_sse(provider: Any, turns: list[dict[str, str]]) -> AsyncIterator[str]:
    try:
        async for event in provider.stream(turns):
            yield sse(event)
    except Exception:
        logger.exception("Chat stream failed")
        yield sse({"type": "error", "message": "Unexpected server error."})
        return
    yield sse({"type": "done"})
