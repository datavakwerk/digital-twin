# Production image: client built statically, served by the FastAPI server.
# Dev uses server/Dockerfile + client/Dockerfile via docker-compose.yml instead.

FROM node:22-alpine AS client
WORKDIR /build
COPY client/package*.json ./
RUN npm ci
COPY client/ .
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev

COPY server/ .
COPY --from=client /build/dist ./static

EXPOSE 3000
CMD ["uv", "run", "--frozen", "--no-dev", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "3000"]