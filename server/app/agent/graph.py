"""The LangGraph agent: state-controlled orchestration of one chat turn.

Graph shape:

    START → guard_input ─┬→ refuse ──────────────────→ END
                         └→ generate ─┬→ execute_tools ─┐
                                      │       ↑─────────┘  (≤ MAX_TOOL_ROUNDS)
                                      └→ verify ────────→ END

Routing, tool execution, and verification are deterministic Python; only
`generate` touches a model, through the provider. Nodes emit SSE-ready
event dicts through LangGraph's custom stream writer; chat.py forwards them
to the browser.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from ..knowledge import KnowledgeDoc
from .guards import looks_like_refusal, screen_input, valid_citation
from .state import AgentState
from .tools import build_tools, tool_definitions

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3

# Answers longer than this without a single citation get flagged for review.
UNCITED_ANSWER_MIN_CHARS = 200

# Numeric meta fields summed across the tool loop's model rounds.
METERED_FIELDS = ("inputTokens", "outputTokens", "cachedTokens", "latencyMs")


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


def _accumulate_meta(totals: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    merged = {key: value for key, value in meta.items() if key != "type"}
    for field in METERED_FIELDS:
        merged[field] = (totals.get(field) or 0) + (meta.get(field) or 0)
    merged["costUsd"] = round((totals.get("costUsd") or 0.0) + (meta.get("costUsd") or 0.0), 5)
    return merged


def _assistant_message(text: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    """The model's tool-calling turn, echoed back in the wire format."""
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["input"])},
            }
            for call in calls
        ],
    }


def _tool_message(call: dict[str, Any], content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call["id"], "content": content}


def build_agent(
    get_provider: Callable[[], Any],
    docs: list[KnowledgeDoc],
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """Compile the agent graph.

    `get_provider` is resolved on every generation so the provider can be
    swapped (tests, future config reload) without rebuilding the graph.
    """
    known_titles = {doc.title for doc in docs}
    tools_by_name = build_tools(docs)
    tool_defs = tool_definitions(tools_by_name)

    async def guard_input(state: AgentState) -> AgentState:
        flags: list[str] = []
        refusal: str | None = None
        if (tripped := screen_input(state["turns"][-1]["content"])) is not None:
            refusal, flag = tripped
            flags.append(flag)
            logger.info("Input guard tripped: %s", flag)
        # Reset per-run state; thread totals (cost, counts) live on.
        return {
            "refusal": refusal,
            "guard_flags": flags,
            "citations": [],
            "last_answer": "",
            "last_meta": None,
            "trace": [],
            "pending_tools": [],
            "loop_messages": [],
            "tool_rounds": 0,
            "loop_meta": None,
        }

    def route_after_guard(state: AgentState) -> str:
        return "refuse" if state.get("refusal") else "generate"

    async def refuse(state: AgentState) -> AgentState:
        get_stream_writer()({"type": "text", "text": state["refusal"]})
        return {"message_count": (state.get("message_count") or 0) + 1}

    async def generate(state: AgentState) -> AgentState:
        writer = get_stream_writer()
        rounds = state.get("tool_rounds") or 0
        kwargs: dict[str, Any] = {"tools": tool_defs, "extension": state.get("loop_messages") or []}
        if rounds >= MAX_TOOL_ROUNDS:
            # Deterministic budget: past the cap the model must answer in text.
            kwargs["tool_choice"] = "none"

        answer = state.get("last_answer") or ""
        citations = list(state.get("citations") or [])
        flags = list(state.get("guard_flags") or [])
        meta_totals = dict(state.get("loop_meta") or {})
        turn: dict[str, Any] = {}
        async for event in get_provider().stream(state["turns"], **kwargs):
            if event["type"] == "turn":
                turn = event
                continue
            if event["type"] == "meta":
                meta_totals = _accumulate_meta(meta_totals, event)
                continue
            if event["type"] == "text":
                answer += event["text"]
            elif event["type"] == "citation":
                if not valid_citation(event.get("title"), known_titles):
                    # Output guard: never surface a citation to a document
                    # that doesn't exist in the knowledge base.
                    flags.append(f"output:unknown-citation:{event.get('title')}")
                    continue
                if event["title"] in citations:
                    continue  # already cited in an earlier round
                citations.append(event["title"])
            writer(event)

        updates: AgentState = {
            "last_answer": answer,
            "citations": citations,
            "guard_flags": flags,
            "loop_meta": meta_totals,
            "pending_tools": [],
        }
        calls = turn.get("toolCalls") or []
        if calls and rounds < MAX_TOOL_ROUNDS:
            updates["pending_tools"] = calls
            updates["loop_messages"] = [
                *(state.get("loop_messages") or []),
                _assistant_message(turn.get("text") or "", calls),
            ]
        else:
            updates["last_meta"] = meta_totals or None
            if meta_totals:
                writer({"type": "meta", **meta_totals})
        return updates

    def route_after_generate(state: AgentState) -> str:
        return "execute_tools" if state.get("pending_tools") else "verify"

    async def execute_tools(state: AgentState) -> AgentState:
        writer = get_stream_writer()
        used = list(state.get("tools_used") or [])
        results = []
        for call in state.get("pending_tools") or []:
            name = call["name"]
            writer({"type": "tool", "name": name})
            used.append(name)
            tool = tools_by_name.get(name)
            if tool is None:
                results.append(_tool_message(call, f"Unknown tool: {name}"))
                continue
            if tool.high_risk:
                # Fail closed: without an explicit approval the action never runs.
                detail = {"status": "declined", "reason": "This action needs Ruud's approval."}
                results.append(_tool_message(call, json.dumps(detail)))
                continue
            try:
                value = await asyncio.wait_for(
                    asyncio.to_thread(tool.run, **call["input"]), timeout=tool.timeout_s
                )
                results.append(_tool_message(call, json.dumps(value)))
            except TimeoutError:
                logger.error("Tool %s timed out after %.1fs", name, tool.timeout_s)
                results.append(_tool_message(call, "Tool timed out."))
            except Exception:
                logger.exception("Tool %s failed", name)
                results.append(_tool_message(call, "Tool failed."))
        return {
            "pending_tools": [],
            "loop_messages": [*(state.get("loop_messages") or []), *results],
            "tool_rounds": (state.get("tool_rounds") or 0) + 1,
            "tools_used": used,
        }

    async def verify(state: AgentState) -> AgentState:
        # Deterministic post-checks and bookkeeping; the run's per-node trace
        # goes out as a diagnostic SSE event.
        cost = (state.get("last_meta") or {}).get("costUsd") or 0.0
        flags = list(state.get("guard_flags") or [])
        answer = state.get("last_answer") or ""
        if (
            len(answer) >= UNCITED_ANSWER_MIN_CHARS
            and not state.get("citations")
            and not state.get("tool_rounds")  # tool results are grounding too
            and not looks_like_refusal(answer)
        ):
            # Groundedness check: a substantive factual answer with zero
            # citations is a hallucination risk — flag it for review.
            flags.append("output:uncited-answer")
            logger.warning("Uncited answer flagged (%d chars)", len(answer))
        get_stream_writer()(
            {
                "type": "trace",
                "nodes": [*(state.get("trace") or []), {"node": "verify", "ms": None}],
                "guardFlags": flags,
            }
        )
        return {
            "guard_flags": flags,
            "message_count": (state.get("message_count") or 0) + 1,
            "total_cost_usd": round((state.get("total_cost_usd") or 0.0) + cost, 5),
        }

    graph = StateGraph(AgentState)
    graph.add_node("guard_input", _traced("guard_input", guard_input))
    graph.add_node("refuse", _traced("refuse", refuse))
    graph.add_node("generate", _traced("generate", generate))
    graph.add_node("execute_tools", _traced("execute_tools", execute_tools))
    graph.add_node("verify", _traced("verify", verify))
    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges("guard_input", route_after_guard, ["refuse", "generate"])
    graph.add_conditional_edges("generate", route_after_generate, ["execute_tools", "verify"])
    graph.add_edge("execute_tools", "generate")
    graph.add_edge("refuse", END)
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=checkpointer)
