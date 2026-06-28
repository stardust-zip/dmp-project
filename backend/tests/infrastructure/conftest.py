import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def postgres_container():
    """
    Starts a PostgreSQL 17-alpine container — matching the production image in
    docker-compose.yml — and keeps it alive for the full test session to avoid
    the overhead of repeated container startup.
    """
    with PostgresContainer("postgres:17-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container():
    """
    Starts a Redis 8.8-alpine container — matching the production image in
    docker-compose.yml — and keeps it alive for the full test session.
    """
    with RedisContainer("redis:8.8-alpine") as r:
        yield r


@pytest.fixture(scope="session")
def pg_engine(postgres_container) -> Engine:
    """
    A SQLAlchemy engine pointed at the session-scoped Postgres container.
    Disposed once at the end of the session rather than per-test to avoid
    the overhead of repeated connection pool creation.
    """
    engine = create_engine(postgres_container.get_connection_url())
    yield engine
    engine.dispose()
