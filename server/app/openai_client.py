"""Minimal raw Chat Completions client: auth, SSE parsing.

Gemini, OpenAI, DeepSeek, and Kimi all speak this protocol. The stream
yields the raw chunk dicts (choices[].delta pieces, then a final chunk
carrying usage). Interpreting them is the provider layer's job.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class OpenAICompatError(Exception):
    pass


class OpenAICompatClient:
    def __init__(self, api_key: str, base_url: str,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=120, transport=transport
        )

    async def stream(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        async with self._client.stream(
            "POST", "/chat/completions", json={**payload, "stream": True},
            headers=self._headers,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")
                raise OpenAICompatError(f"API {response.status_code}: {body[:500]}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                yield json.loads(data)

    async def close(self) -> None:
        await self._client.aclose()
