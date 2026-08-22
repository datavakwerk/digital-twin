import json
from typing import Any

import httpx


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
         "usage": {"prompt_tokens": 100, "completion_tokens": 50}},
    ]


def fake_transport(chunks: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=sse_bytes(chunks),
            headers={"content-type": "text/event-stream"},
        )

    return httpx.MockTransport(handler)
