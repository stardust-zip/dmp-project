import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from src.core.config import settings

DATABASE_URL = os.getenv("DATABASE_URL", settings.DATABASE_URL)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Locate alembic.ini relative to this file (backend/src/database.py -> backend/../alembic.ini)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI_PATH = _PROJECT_ROOT / "alembic.ini"


def _make_alembic_config() -> Config:
    """Create an Alembic Config pointing to our alembic.ini and DB URL."""
    if _ALEMBIC_INI_PATH.exists():
        alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
    else:
        # Fallback: construct config manually (e.g. if running outside the project root)
        alembic_cfg = Config()
        alembic_cfg.set_main_option(
            "script_location", str(_PROJECT_ROOT / "backend" / "alembic")
        )
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    return alembic_cfg


def _stamp_head():
    """Stamp the alembic_version table to the current head revision.

    This is needed when the database has a stale / orphaned revision
    (e.g. from a pre-Alembic era or a migration file that was renamed).
    """
    try:
        alembic_cfg = _make_alembic_config()
        command.stamp(alembic_cfg, "head")
    except Exception:
        pass


def init_db():
    """Applies Alembic migrations to bring the database schema to head.

    Also applies any missing columns that may exist in the model but aren't
    yet reflected in the database (handles migration drift from the pre-Alembic
    era).
    """
    alembic_cfg = _make_alembic_config()

    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        import logging

        exc_text = str(exc)
        # If the database has a stale revision identifier, stamp head first
        if "Can't locate revision" in exc_text:
            logging.getLogger(__name__).warning(
                "Stale alembic revision detected; re-stamping to head. (%s)",
                exc_text,
            )
            _stamp_head()
            # Retry the upgrade after stamping — this will be a no-op if the
            # head was already the current revision, so we always sync columns
            # directly afterward.
            try:
                command.upgrade(alembic_cfg, "head")
            except Exception as retry_exc:
                logging.getLogger(__name__).warning(
                    "Alembic upgrade still failed after re-stamp (%s); "
                    "falling back to direct schema sync.",
                    retry_exc,
                )
            # Stamping skips the actual migration content; ensure all expected
            # columns are present via direct ALTER TABLE.
            _ensure_user_profile_columns()
        else:
            logging.getLogger(__name__).warning(
                "Alembic migration failed (%s); falling back to direct schema sync.",
                exc,
            )
            _ensure_user_profile_columns()


def _ensure_user_profile_columns():
    """Add missing user-profile columns that the ORM model expects.

    This is a safety net for databases that were created before the Alembic
    migration was introduced, or whose migration file was modified in-place
    after having already been stamped.
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    statements: list[str] = []

    if "contact_number" not in existing_columns:
        statements.append("ALTER TABLE users ADD COLUMN contact_number VARCHAR")
    if "status" not in existing_columns:
        if engine.dialect.name == "postgresql":
            # Create the enum type first if it doesn't exist
            statements.append(
                "DO $$ BEGIN CREATE TYPE user_status AS ENUM ("
                "'Available', 'In_Shift', 'Busy', 'On_Break', 'Off_Duty', 'On_Leave', 'Suspended'"
                "); EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
            statements.append(
                "ALTER TABLE users ADD COLUMN status user_status NOT NULL DEFAULT 'Off_Duty'"
            )
        else:
            statements.append(
                "ALTER TABLE users ADD COLUMN status VARCHAR NOT NULL DEFAULT 'Off_Duty'"
            )
    if "assigned_site_ids" not in existing_columns:
        if engine.dialect.name == "postgresql":
            statements.append(
                "ALTER TABLE users ADD COLUMN assigned_site_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        else:
            statements.append(
                "ALTER TABLE users ADD COLUMN assigned_site_ids JSON NOT NULL DEFAULT '[]'"
            )
    if "is_global_admin" not in existing_columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN is_global_admin BOOLEAN NOT NULL DEFAULT false"
        )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db():
    """Dependency to provide a DB session to FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
