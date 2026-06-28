"""Alembic environment configuration for DMP Smart City AI Platform.

This module configures Alembic to auto-detect all SQLAlchemy models
defined in src.models and generate migrations based on schema changes.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config object
config = context.config

# Set the SQLAlchemy URL from environment variable with fallback to alembic.ini
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://dmp_user:dmp_password@localhost:5432/dmp_db",
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so Base.metadata is fully populated
# Must import Base and ALL model modules for auto-generation to work
# Import models module to ensure all model classes are registered on Base.metadata
import src.models  # noqa: E402, F401
from src.models import Base  # noqa: E402

target_metadata = Base.metadata

# Read version_table from alembic.ini to avoid conflicts with other applications
# sharing the same database (e.g., MLflow uses its own alembic_version table).
VERSION_TABLE = config.get_main_option("version_table", "alembic_version")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without connecting to DB)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB and apply)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
