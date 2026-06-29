"""
Infrastructure tests: external service connectivity.

These tests spin up real Postgres and Redis containers (via testcontainers)
and verify that the platform's runtime dependencies are reachable, return
correct protocol responses, and meet the minimum version requirements
declared in docker-compose.yml.
"""

import redis as redis_client
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# PostgreSQL connectivity
# ---------------------------------------------------------------------------


def test_postgres_container_accepts_tcp_connections(postgres_container):
    """Engine creation and a trivial query must succeed without exception."""
    engine = create_engine(postgres_container.get_connection_url())
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
    engine.dispose()


def test_postgres_server_version_meets_minimum_requirement(postgres_container):
    """
    The running Postgres instance must be version 15 or higher.
    The project uses JSONB and composite PKs that rely on PG 12+ features,
    but we enforce 15+ to match what CI and production docker-compose use.
    """
    engine = create_engine(postgres_container.get_connection_url())
    with engine.connect() as conn:
        version_string = conn.execute(text("SHOW server_version")).scalar()
    engine.dispose()

    major_version = int(version_string.split(".")[0])
    assert major_version >= 15, (
        f"Expected PostgreSQL >= 15, but container is running {version_string}"
    )


def test_postgres_supports_jsonb_column_type(postgres_container):
    """
    JSONB is used in users.assigned_site_ids, system_log.details, and
    other columns.  This probe ensures the connected Postgres dialect
    supports it before any ORM schema is applied.
    """
    engine = create_engine(postgres_container.get_connection_url())
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS _jsonb_probe (data JSONB)"))
        conn.execute(text("DROP TABLE _jsonb_probe"))
    engine.dispose()


def test_postgres_supports_uuid_generation(postgres_container):
    """
    Several primary-key columns (users.id, ai_pipeline_log.id, etc.) use
    server-side UUID generation.  Verify the pg_catalog function is available.
    """
    engine = create_engine(postgres_container.get_connection_url())
    with engine.connect() as conn:
        result = conn.execute(text("SELECT gen_random_uuid()")).scalar()
    engine.dispose()
    assert result is not None


# ---------------------------------------------------------------------------
# Redis connectivity
# ---------------------------------------------------------------------------


def _make_redis_client(redis_container) -> redis_client.Redis:
    """Creates a decode_responses=True Redis client pointed at the container."""
    return redis_client.Redis(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(6379)),
        decode_responses=True,
    )


def test_redis_container_responds_to_ping(redis_container):
    """A PING command to the Redis container must return True."""
    client = _make_redis_client(redis_container)
    try:
        assert client.ping()
    finally:
        client.close()


def test_redis_can_write_and_read_back_a_string_key(redis_container):
    """
    Basic SET/GET round-trip must work.
    Celery uses Redis as its message broker and result backend — both rely
    on this fundamental operation.
    """
    client = _make_redis_client(redis_container)
    test_key = "infra:portability_probe"
    test_value = "dmp_platform_ok"
    try:
        client.set(test_key, test_value, ex=30)
        assert client.get(test_key) == test_value
    finally:
        client.delete(test_key)
        client.close()


def test_redis_key_ttl_is_honoured(redis_container):
    """
    Celery stores task results with an expiry (CELERY_TASK_RESULT_EXPIRES).
    Verify that the TTL mechanism is functional in the running instance.
    """
    client = _make_redis_client(redis_container)
    probe_key = "infra:ttl_probe"
    try:
        client.set(probe_key, "ephemeral", ex=60)
        remaining_ttl = client.ttl(probe_key)
    finally:
        client.delete(probe_key)
        client.close()

    assert 0 < remaining_ttl <= 60


def test_redis_key_deletion_removes_the_key(redis_container):
    """DEL must completely remove the key — no phantom reads after deletion."""
    client = _make_redis_client(redis_container)
    probe_key = "infra:delete_probe"
    try:
        client.set(probe_key, "present", ex=30)
        client.delete(probe_key)
        assert client.get(probe_key) is None
    finally:
        client.close()


def test_redis_supports_list_operations_used_by_celery(redis_container):
    """
    Celery's default broker queue is a Redis List.  LPUSH / BRPOP must work.
    """
    client = _make_redis_client(redis_container)
    queue_key = "infra:queue_probe"
    try:
        client.lpush(queue_key, "task_payload")
        payload = client.rpop(queue_key)
    finally:
        client.delete(queue_key)
        client.close()

    assert payload == "task_payload"
