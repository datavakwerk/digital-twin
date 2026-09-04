import json
from typing import Any

import httpx
import pytest

from app.rate_limit import limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    limiter.reset()

def sse_bytes(chunks: list[dict[str, Any]]) -> bytes:
    """Encode chunk dicts as an OpenAI-style SSE response body."""
    body = b"".join(f"data: {json.dumps(c)}\n\n".encode() for c in chunks)
    return body + b"data: [DONE]\n\n"


def text_stream(text: str) -> list[dict[str, Any]]:
    """A minimal complete chunk sequence for one text answer."""
    return [
        {"choices": [{"index": 0, "delta": {"content": text},
                      "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [],
         "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                   "prompt_tokens_details": {"cached_tokens": 75}}},
    ]


def fake_transport(chunks: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=sse_bytes(chunks),
            headers={"content-type": "text/event-stream"},
        )

    return httpx.MockTransport(handler)

def parse_events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[len("data: "):])
            for line in body.splitlines() if line.startswith("data: ")]


def visible(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop diagnostic trace events; most tests assert the visitor-facing stream."""
    return [e for e in events if e["type"] != "trace"]
