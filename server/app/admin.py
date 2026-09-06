"""Admin endpoints: Ruud approves or rejects paused high-risk actions.

A high-risk tool call interrupts the graph mid-run; the thread sits
checkpointed until a decision arrives here. Approving (or rejecting) resumes
the graph from the checkpoint — the tool executes (or is declined) and the
model finishes its answer into the thread state.

Protected by a bearer token (ADMIN_TOKEN). No token configured → endpoints
off. The pending queue is an in-memory dict on app.state until Phase 9 makes
it durable.
"""

import logging
from typing import Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from .config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")

THREAD_ID = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=500)


def _unauthorized(request: Request) -> JSONResponse | None:
    token = get_settings().admin_token
    if not token:
        return JSONResponse(status_code=403, content={"error": "Admin endpoints are disabled."})
    if request.headers.get("authorization") != f"Bearer {token}":
        return JSONResponse(status_code=401, content={"error": "Unauthorized."})
    return None


@router.get("/approvals")
async def list_approvals(request: Request) -> Any:
    if (denied := _unauthorized(request)) is not None:
        return denied
    return {"pending": list(request.app.state.approvals.values())}


@router.post("/approvals/{thread_id}")
async def decide_approval(
    request: Request, decision: ApprovalDecision, thread_id: str = THREAD_ID
) -> Any:
    if (denied := _unauthorized(request)) is not None:
        return denied

    agent = request.app.state.agent
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await agent.aget_state(config)
    if not snapshot.interrupts:
        return JSONResponse(
            status_code=404, content={"error": "No pending approval for this thread."}
        )

    # Resume from the checkpoint; interrupt() in the graph returns this value.
    resume = Command(resume={"approved": decision.approved, "note": decision.note})
    answer: list[str] = []
    async for event in agent.astream(resume, config, stream_mode="custom"):
        if event.get("type") == "text":
            answer.append(event["text"])

    request.app.state.approvals.pop(thread_id, None)
    status = "approved" if decision.approved else "rejected"
    logger.info("Approval %s for thread %s", status, thread_id)
    return {"status": status, "thread_id": thread_id, "answer": "".join(answer)}
