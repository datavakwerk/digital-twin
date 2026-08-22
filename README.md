# digital-twin

An AI assistant for ruudjuffermans.nl that answers questions about
Ruud's work, grounded in his real CV and writing. Implements the P0 core of the
PRD: streaming responses, native citations, prompt caching, honest refusals,
rate limiting, and per-message cost telemetry.

## Setup

```bash
cp .env.example .env   # add your LLM api keys
```

### Switching LLMs

The model backend is pluggable. Set `LLM_PROVIDER` in
`.env` to switch — no code changes:

```bash
# .env
LLM_PROVIDER=gemini                     # default: deepseek
OLLAMA_MODEL=gemini-3.1-flash-lite      # local model to use
```