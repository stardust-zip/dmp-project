FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./

ENV UV_HTTP_TIMEOUT=300

RUN uv pip install --system -r pyproject.toml

COPY backend/src ./src
