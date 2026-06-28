"""System status endpoint for DMP Smart City AI Platform.

Provides deployment readiness information consumed by the ``./setup`` script:
database connectivity, Alembic migration state, and DVC data availability.

This endpoint is intentionally kept as a standalone module with zero
dependency on other API endpoint modules, so it can be registered
independently.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import inspect, text

from src.database import engine, _ALEMBIC_INI_PATH

router = APIRouter(prefix="/system", tags=["system"])


# ─── Helpers ────────────────────────────────────────────────────────────────


_ALEMBIC_VERSION_TABLE = "dmp_alembic_version"


def _get_alembic_status() -> dict:
    """Query dmp_alembic_version table and migration files to determine state.

    Uses the custom table name configured in alembic.ini (version_table =
    dmp_alembic_version) to avoid conflicting with MLflow's own alembic_version
    table in the shared database.
    """
    try:
        with engine.connect() as conn:
            inspector = inspect(engine)
            table_names = inspector.get_table_names()

            # dmp_alembic_version is absent — migrations have never run.
            if _ALEMBIC_VERSION_TABLE not in table_names:
                return {
                    "current_revision": None,
                    "head_revision": _resolve_head_revision(),
                    "pending_migrations": -1,
                }

            # Current revision applied in the database.
            result = conn.execute(
                text(f"SELECT version_num FROM {_ALEMBIC_VERSION_TABLE}")
            )
            current: str | None = result.scalar()

            # Head revision from the most recent migration file.
            head: str | None = _resolve_head_revision()

            # Determine pending count: 0 if up-to-date, 1+ if behind, -1 if unknown.
            pending = -1
            if current and head:
                pending = 0 if current == head else 1

            return {
                "current_revision": current,
                "head_revision": head,
                "pending_migrations": pending,
            }

    except Exception as exc:
        return {
            "current_revision": None,
            "head_revision": None,
            "pending_migrations": -1,
            "error": str(exc),
        }


def _resolve_head_revision() -> str | None:
    """Parse the head revision ID from the most recent migration file.

    Uses Alembic's ScriptDirectory if available, otherwise falls back
    to sorting filenames in the versions directory.
    """
    versions_dir = Path(_ALEMBIC_INI_PATH).parent / "alembic" / "versions"

    if not versions_dir.is_dir():
        return None

    try:
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(
            _alembic_config(str(_ALEMBIC_INI_PATH))
        )
        head = script.get_current_head()
        if head:
            return head
    except Exception:
        pass

    # Fallback: parse filename — first segment before '_' is the revision ID.
    migration_files = sorted(
        [f for f in os.listdir(versions_dir) if f.endswith(".py")],
        reverse=True,
    )
    if migration_files:
        return migration_files[0].split("_", maxsplit=1)[0]

    return None


def _alembic_config(ini_path: str):
    """Lazily build an Alembic Config for ScriptDirectory resolution."""
    from alembic.config import Config

    cfg = Config(ini_path)
    cfg.set_main_option(
        "sqlalchemy.url",
        os.getenv("DATABASE_URL", "postgresql://dmp_user:dmp_password@localhost:5432/dmp_db"),
    )
    return cfg


def _get_dvc_status() -> dict:
    """Check whether DVC-tracked data is available on disk."""
    data_path = os.getenv("DATA_PATH", "/app/data/raw/data")
    data_available = False
    last_pull: str | None = None

    if os.path.isdir(data_path) and os.listdir(data_path):
        data_available = True
        try:
            latest = max(
                os.path.getmtime(os.path.join(data_path, entry))
                for entry in os.listdir(data_path)
            )
            last_pull = datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            pass

    return {
        "data_available": data_available,
        "data_path": data_path,
        "last_pull": last_pull,
    }


# ─── Endpoint ───────────────────────────────────────────────────────────────


@router.get("/status")
def system_status() -> dict:
    """Return system health and configuration status.

    Used by the ``./setup`` script to verify deployment readiness after
    starting services.  Returns database connectivity, Alembic migration
    state, and DVC data availability in a single response.
    """
    db_connected = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        pass

    return {
        "service": "dmp-backend",
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "database": {
            "connected": db_connected,
            **_get_alembic_status(),
        },
        "dvc": _get_dvc_status(),
    }
