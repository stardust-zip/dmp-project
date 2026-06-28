#!/usr/bin/env bash
# ==============================================================================
# Backend Entrypoint — Idempotent & Portable Startup
# ==============================================================================
# Handles all database-migration states safely, including:
#   - Fresh database (no tables)                  → alembic upgrade head
#   - Correct version stamped                     → alembic upgrade head (no-op)
#   - Orphaned version + no app tables            → clear version, alembic upgrade
#   - Orphaned version + app tables exist         → clear version, stamp head
#   - App tables exist, no version table          → stamp head
#   - Migration fails (e.g., stale enum types)    → clean orphaned types, retry
# ==============================================================================
set -euo pipefail

echo "[entrypoint] Checking database migration state..."

# Step 1: If the alembic version in the DB is orphaned (doesn't exist in our
# migration scripts), clean it up so alembic doesn't crash on startup.
fix_orphaned_version() {
    python -c "
from alembic.script import ScriptDirectory
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
import os, sys

# Derive the expected table names from the models themselves so this check
# stays correct automatically as the schema evolves — never hard-code them.
import src.models
from src.models import Base
EXPECTED_APP_TABLES = set(Base.metadata.tables.keys())

engine = create_engine(os.environ['DATABASE_URL'])
insp = inspect(engine)

if 'dmp_alembic_version' not in insp.get_table_names():
    sys.exit(0)  # No version table yet — nothing to fix

with engine.connect() as conn:
    result = conn.execute(text('SELECT version_num FROM dmp_alembic_version'))
    row = result.fetchone()
    if not row:
        sys.exit(0)  # Empty version table

    db_version = row[0]
    config = Config('alembic.ini')
    script = ScriptDirectory.from_config(config)

    try:
        script.get_revision(db_version)
        sys.exit(0)  # Revision exists — all good
    except Exception:
        # Orphaned revision — delete it
        existing = set(insp.get_table_names())
        has_app_tables = bool(EXPECTED_APP_TABLES & existing)

        print(f'[entrypoint] Orphaned alembic version ({db_version}) detected.')
        conn.execute(text('DELETE FROM dmp_alembic_version'))
        conn.commit()

        if has_app_tables:
            print('[entrypoint] App tables exist — will re-stamp head after cleanup.')
        else:
            print('[entrypoint] No app tables — will run fresh migration after cleanup.')
"
}

# Step 2: If application tables exist but the version table has no entry,
# stamp the current head so alembic knows the migration was already applied.
stamp_if_needed() {
    python -c "
from sqlalchemy import create_engine, inspect, text
import os, sys

# Same as fix_orphaned_version: derive expected tables from the models so the
# detection stays in sync with the schema without any manual list to maintain.
import src.models
from src.models import Base
EXPECTED_APP_TABLES = set(Base.metadata.tables.keys())

engine = create_engine(os.environ['DATABASE_URL'])
insp = inspect(engine)
tables = set(insp.get_table_names())

has_app_tables = bool(EXPECTED_APP_TABLES & tables)
if not has_app_tables:
    sys.exit(1)  # No app tables — let alembic upgrade handle it

version_table = 'dmp_alembic_version'
if version_table not in tables:
    print('[entrypoint] App tables exist but no version table — stamping head.')
    sys.exit(0)

# Check if version table is empty
with engine.connect() as conn:
    result = conn.execute(text(f'SELECT 1 FROM {version_table} LIMIT 1'))
    if not result.fetchone():
        print('[entrypoint] App tables exist but version table is empty — stamping head.')
        sys.exit(0)

sys.exit(1)  # Version table has a valid entry — nothing to stamp
" && {
        alembic stamp head
        echo '[entrypoint] ✓ Head stamped.'
    } || true
}

# ── Main ──────────────────────────────────────────────────────────────────────
fix_orphaned_version
stamp_if_needed

echo "[entrypoint] Running migrations..."
if alembic upgrade head 2>&1 | tee /tmp/alembic_output.log; then
    echo "[entrypoint] ✓ Migrations complete."
else
    # If the migration failed because enum types already exist (e.g., after a
    # manual table drop that left orphaned types), clean them and retry once.
    if grep -q 'already exists' /tmp/alembic_output.log 2>/dev/null; then
        echo "[entrypoint] Migration failed — cleaning up orphaned database types..."
        python -c "
from sqlalchemy import create_engine, text
import os
engine = create_engine(os.environ['DATABASE_URL'])
with engine.connect() as conn:
    for t in ('job_type', 'model_task', 'job_status', 'drift_type', 'drift_severity',
              'user_role', 'user_status', 'alert_severity', 'alert_status', 'ingestion_status'):
        conn.execute(text(f'DROP TYPE IF EXISTS {t} CASCADE'))
    conn.commit()
print('[entrypoint] ✓ Orphaned types cleaned.')
"
        echo "[entrypoint] Retrying migration..."
        alembic upgrade head
        echo "[entrypoint] ✓ Migrations complete."
    else
        echo "[entrypoint] ❌ Migration failed with unknown error:"
        cat /tmp/alembic_output.log
        exit 1
    fi
fi

echo "[entrypoint] Seeding default users..."
python -m src.seeders.users
echo "[entrypoint] ✓ Users seeded."

echo "[entrypoint] Starting Uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
