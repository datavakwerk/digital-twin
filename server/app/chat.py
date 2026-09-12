import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import get_settings
from .db import record_feedback
from .rate_limit import limiter
from .schemas import ChatRequest, FeedbackRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

APPROVAL_NOTICE = (
    "\n\nThis request needs Ruud's personal approval — it has been queued for his review."
)


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/feedback")
@limiter.limit(get_settings().rate_limit)
async def feedback(request: Request, payload: FeedbackRequest) -> Response:
    """👍/👎 per answer; needs the database (the row is the whole point)."""
    sessions = request.app.state.sessions
    if sessions is None:
        return JSONResponse(
            status_code=503, content={"error": "Feedback is not available right now."}
        )
    await record_feedback(
        sessions,
        thread_id=payload.thread_id,
        verdict=payload.verdict,
        question=payload.question,
        answer=payload.answer,
        comment=payload.comment,
    )
    return Response(status_code=204)


@router.post("/chat")
@limiter.limit(get_settings().rate_limit)
async def chat(request: Request, payload: ChatRequest) -> StreamingResponse:
    turns = [{"role": t.role, "content": t.content} for t in payload.messages]
    thread_id = payload.thread_id or uuid4().hex
    return StreamingResponse(
        stream_sse(request.app.state, turns, thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def stream_sse(
    app_state: Any, turns: list[dict[str, str]], thread_id: str
) -> AsyncIterator[str]:
    agent = app_state.agent
    config = {"configurable": {"thread_id": thread_id}}
    # Gathered along the way for the turn log; the visitor only sees the events.
    outcome = "answered"
    meta: dict[str, Any] | None = None
    tools_used: list[str] = []
    guard_flags: list[str] = []
    answer = ""
    try:
        async for event in agent.astream({"turns": turns}, config, stream_mode="custom"):
            if event["type"] == "meta":
                meta = event
            elif event["type"] == "tool":
                tools_used.append(event["name"])
            elif event["type"] == "text":
                answer += event["text"]
            yield sse(event)
        snapshot = await agent.aget_state(config)
        guard_flags = list(snapshot.values.get("guard_flags") or [])
        if snapshot.values.get("refusal"):
            outcome = "refused"
        if snapshot.interrupts:
            # A high-risk tool paused the graph for Ruud's approval. Queue it
            # for the admin endpoint (durable with a database) and tell the visitor.
            outcome = "pending_approval"
            await app_state.approvals.add(thread_id, snapshot.interrupts[0].value or {})
            yield sse({"type": "text", "text": APPROVAL_NOTICE})
            yield sse({"type": "approval", "status": "pending"})
    except Exception:
        logger.exception("Chat stream failed")
        outcome = "error"
        yield sse({"type": "error", "message": "Unexpected server error."})
    else:
        yield sse({"type": "done"})
    if app_state.recorder is not None:
        # Turn log + budget ledger + guard incidents + unanswered questions;
        # best-effort, never raises.
        await app_state.recorder.record(
            thread_id=thread_id,
            outcome=outcome,
            meta=meta,
            tools_used=tools_used,
            guard_flags=guard_flags,
            visitor_message=turns[-1]["content"],
            answer=answer,
        )
