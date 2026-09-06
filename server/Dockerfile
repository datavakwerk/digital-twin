FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies first, so this layer caches independently of source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 3000
CMD ["uv", "run", "--frozen", "--no-dev", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "3000", "--reload"]