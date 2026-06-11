FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv pip install --system -r pyproject.toml

COPY alembic.ini ./
COPY backend/alembic ./backend/alembic
COPY backend/src ./src
