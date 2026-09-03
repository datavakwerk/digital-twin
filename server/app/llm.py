"""Provider layer: build the grounded prompt, translate raw API chunks
into simple client events: {type: text|meta|error}.

Pick a provider with LLM_PROVIDER in .env — gemini (default), openai,
deepseek, or kimi. All speak the same chat-completions protocol.
"""

import time
from collections.abc import AsyncIterator
from typing import Any

from .config import Settings
from .knowledge import KnowledgeDoc
from .openai_client import OpenAICompatClient
from .pricing import cost_usd

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_field": "gemini_api_key", "model_field": "gemini_model",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_field": "openai_api_key", "model_field": "openai_model",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "key_field": "deepseek_api_key", "model_field": "deepseek_model",
    },
    "kimi": {
        "base_url": "https://api.moonshot.ai/v1",
        "key_field": "moonshot_api_key", "model_field": "kimi_model",
    },
}

SYSTEM_PROMPT = """You are "Digital Twin", an AI assistant on Ruud Juffermans's
website, answering visitors' questions about Ruud and his work.

- Ground every factual claim about Ruud in the provided documents. When you
  state a fact from a document, name the document title inline.
- If the documents don't contain the answer, say so plainly and suggest
  contacting Ruud directly. Never invent facts.
- Stay on topic: Ruud and his work. Politely decline anything else.
- Be concise and friendly."""


def _cached_tokens(usage: dict[str, Any]) -> int:
    # Gemini, OpenAI, and Kimi report cache hits in prompt_tokens_details;
    # DeepSeek uses its own top-level field.
    details = usage.get("prompt_tokens_details") or {}
    return details.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0

def knowledge_system_prompt(docs: list[KnowledgeDoc]) -> str:
    # The chat-completions protocol has no document blocks; the knowledge
    # base rides in the system prompt as titled markdown sections.
    sections = "\n\n---\n\n".join(f"# {doc.title}\n\n{doc.text}" for doc in docs)
    return f"{SYSTEM_PROMPT}\n\nKnowledge base documents:\n\n{sections}"


class OpenAICompatProvider:
    def __init__(self, settings: Settings, docs: list[KnowledgeDoc],
                 client: OpenAICompatClient | None = None):
        spec = PROVIDERS[settings.llm_provider]
        self._model = getattr(settings, spec["model_field"])
        self._provider = settings.llm_provider
        # OpenAI's current models reject max_tokens in favor of the newer name.
        self._cap = ("max_completion_tokens" if settings.llm_provider == "openai"
                     else "max_tokens")
        self._max_output_tokens = settings.max_output_tokens
        self._titles = [doc.title for doc in docs]
        self._system = knowledge_system_prompt(docs)
        self.client = client or OpenAICompatClient(
            api_key=getattr(settings, spec["key_field"]),
            base_url=spec["base_url"],
        )

    async def stream(self, turns: list[dict[str, str]]) -> AsyncIterator[dict[str, Any]]:
        payload = {
            "model": self._model,
            self._cap: self._max_output_tokens,
            "messages": [{"role": "system", "content": self._system}, *turns],
            # ask for the final usage-bearing chunk
            "stream_options": {"include_usage": True},
        }
        started = time.monotonic()
        model = self._model
        usage: dict[str, Any] = {}
        answer = ""
        cited: set[str] = set()
        async for chunk in self.client.stream(payload):
            model = chunk.get("model") or model
            if chunk.get("usage"):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    answer += delta["content"]
                    yield {"type": "text", "text": delta["content"]}
                    for title in self._titles:
                        if title not in cited and title in answer:
                            cited.add(title)
                            yield {"type": "citation", "title": title}
        input_tokens = usage.get("prompt_tokens") or 0
        output_tokens = usage.get("completion_tokens") or 0
        yield {
            "type": "meta",
            "model": model,
            "latencyMs": round((time.monotonic() - started) * 1000),
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cachedTokens": _cached_tokens(usage),
            "costUsd": round(cost_usd(self._provider, input_tokens, output_tokens), 5),
        }

    async def close(self) -> None:
        await self.client.close()
