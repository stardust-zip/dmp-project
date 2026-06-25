FROM ghcr.io/astral-sh/uv:python3.12-bookworm

WORKDIR /app

# Copy dependency files first for better Docker layer caching
COPY pyproject.toml uv.lock ./

ENV UV_HTTP_TIMEOUT=300

# Install dependencies into a virtual environment (not system Python)
RUN uv sync --frozen

# Copy application code
COPY backend/src ./src
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic

# Use the virtual environment Python
ENV PATH="/app/.venv/bin:$PATH"

# Default command (overridden by docker-compose.yml)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
