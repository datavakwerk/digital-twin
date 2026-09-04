"""The LangGraph agent: state-controlled orchestration of one chat turn.

Graph shape:

    START → guard_input ─┬→ refuse ──→ END
                         └→ generate ─→ verify ──→ END

Routing and verification are deterministic Python; only `generate` touches
a model, through the provider. Nodes emit SSE-ready event dicts through
LangGraph's custom stream writer; chat.py forwards them to the browser.
"""

import time
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from .state import AgentState


def _traced(name: str, fn: Callable[[AgentState], Any]) -> Callable[[AgentState], Any]:
    """Record per-node latency into the run's trace."""

    async def wrapper(state: AgentState) -> AgentState:
        started = time.perf_counter()
        updates: AgentState = await fn(state) or {}
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        base = updates.get("trace", state.get("trace") or [])
        updates["trace"] = [*base, {"node": name, "ms": elapsed_ms}]
        return updates

    return wrapper


def build_agent(
    get_provider: Callable[[], Any],
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """Compile the agent graph.

    `get_provider` is resolved on every generation so the provider can be
    swapped (tests, future config reload) without rebuilding the graph.
    """

    async def guard_input(_state: AgentState) -> AgentState:
        # Reset per-run state; thread totals (cost, counts) live on.
        return {
            "refusal": None,
            "guard_flags": [],
            "citations": [],
            "last_answer": "",
            "last_meta": None,
            "trace": [],
        }

    def route_after_guard(state: AgentState) -> str:
        return "refuse" if state.get("refusal") else "generate"

    async def refuse(state: AgentState) -> AgentState:
        get_stream_writer()({"type": "text", "text": state["refusal"]})
        return {"message_count": (state.get("message_count") or 0) + 1}

    async def generate(state: AgentState) -> AgentState:
        writer = get_stream_writer()
        answer = ""
        citations: list[str] = []
        meta: dict[str, Any] | None = None
        async for event in get_provider().stream(state["turns"]):
            if event["type"] == "meta":
                meta = event  # held back until the answer is complete
                continue
            if event["type"] == "text":
                answer += event["text"]
            elif event["type"] == "citation":
                citations.append(event["title"])
            writer(event)
        if meta:
            writer(meta)
        return {"last_answer": answer, "citations": citations, "last_meta": meta}

    async def verify(state: AgentState) -> AgentState:
        # Deterministic post-checks and bookkeeping; the run's per-node trace
        # goes out as a diagnostic SSE event.
        cost = (state.get("last_meta") or {}).get("costUsd") or 0.0
        get_stream_writer()(
            {
                "type": "trace",
                "nodes": [*(state.get("trace") or []), {"node": "verify", "ms": None}],
                "guardFlags": list(state.get("guard_flags") or []),
            }
        )
        return {
            "message_count": (state.get("message_count") or 0) + 1,
            "total_cost_usd": round((state.get("total_cost_usd") or 0.0) + cost, 5),
        }

    graph = StateGraph(AgentState)
    graph.add_node("guard_input", _traced("guard_input", guard_input))
    graph.add_node("refuse", _traced("refuse", refuse))
    graph.add_node("generate", _traced("generate", generate))
    graph.add_node("verify", _traced("verify", verify))
    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges("guard_input", route_after_guard, ["refuse", "generate"])
    graph.add_edge("generate", "verify")
    graph.add_edge("refuse", END)
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=checkpointer)
