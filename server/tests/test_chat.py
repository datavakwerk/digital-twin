import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.openai_client import OpenAICompatClient
from tests.conftest import fake_transport, text_stream


def parse_events(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):])
            for line in body.splitlines() if line.startswith("data: ")]


def test_chat_streams_text_meta_done():
    with TestClient(create_app()) as client:
        client.app.state.llm.client = OpenAICompatClient(
            api_key="k", base_url="https://example.test/v1",
            transport=fake_transport(text_stream("Hello there.")),
        )
        response = client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Who is Ruud?"}]
        })

    events = parse_events(response.text)
    assert [e["type"] for e in events] == ["text", "meta", "done"]
    assert events[0]["text"] == "Hello there."
    assert events[1]["inputTokens"] == 100


def test_invalid_payload_is_rejected():
    with TestClient(create_app()) as client:
        assert client.post("/api/chat", json={"messages": []}).status_code == 422
