import asyncio

import httpx
import pytest

from app.openai_client import OpenAICompatClient, OpenAICompatError
from tests.conftest import fake_transport, text_stream


def make_client(transport: httpx.AsyncBaseTransport) -> OpenAICompatClient:
    return OpenAICompatClient(
        api_key="k", base_url="https://example.test/v1", transport=transport
    )


def test_stream_parses_sse_chunks():
    client = make_client(fake_transport(text_stream("hi")))

    async def collect():
        return [c async for c in client.stream({"model": "m", "messages": []})]

    chunks = asyncio.run(collect())
    assert len(chunks) == 3  # [DONE] is consumed, never yielded
    assert chunks[0]["choices"][0]["delta"]["content"] == "hi"
    assert chunks[-1]["usage"]["completion_tokens"] == 50


def test_error_status_raises():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": "no key"})
    )
    client = make_client(transport)

    async def run():
        async for _ in client.stream({"model": "m", "messages": []}):
            pass

    with pytest.raises(OpenAICompatError):
        asyncio.run(run())
