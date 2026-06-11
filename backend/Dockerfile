FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN for i in 1 2 3; do uv pip install --system -r pyproject.toml && break || sleep $((i * 5)); done

COPY alembic.ini ./
COPY backend/alembic ./backend/alembic
COPY backend/src ./src
