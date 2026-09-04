import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

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
    thread_id = payload.thread_id or uuid4().hex
    return StreamingResponse(
        stream_sse(request.app.state.agent, turns, thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def stream_sse(agent: Any, turns: list[dict[str, str]], thread_id: str) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": thread_id}}
    try:
        async for event in agent.astream({"turns": turns}, config, stream_mode="custom"):
            yield sse(event)
    except Exception:
        logger.exception("Chat stream failed")
        yield sse({"type": "error", "message": "Unexpected server error."})
        return
    yield sse({"type": "done"})
