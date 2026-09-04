"""Typed state flowing through the LangGraph agent.

One AgentState per conversation thread. With a checkpointer attached it is
persisted per `thread_id`, so the running totals accumulate across turns.
Per-run fields are reset by `guard_input` at the start of every run.
"""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # The full conversation for this turn (the client sends complete history).
    turns: list[dict[str, str]]
    # Set by guard_input; non-None routes to the deterministic refuse node.
    refusal: str | None
    # Guards that tripped during this run, e.g. "input:injection".
    guard_flags: list[str]
    # Document titles cited in this run's answer.
    citations: list[str]
    # Full answer text of this run (for deterministic output checks).
    last_answer: str
    # Usage/cost/latency telemetry of this run's generation.
    last_meta: dict[str, Any] | None
    # Per-node latency of this run: [{"node": name, "ms": float}].
    trace: list[dict[str, Any]]
    # Accumulated across the thread's lifetime (checkpointed).
    total_cost_usd: float
    message_count: int
