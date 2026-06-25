# Implementation Plan: Project Portability

**Based on:** [`docs/architecture/portability.md`](./portability.md)
**Status:** In progress (Phases 1-5 completed)
**Last Updated:** 2026-06-25
**Created:** 2026-06-25

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Pre-Implementation Checklist](#2-pre-implementation-checklist)
3. [Phase 1: Docker Compose Profiles (2-3 hours)](#3-phase-1-docker-compose-profiles)
4. [Phase 2: The `setup` Entrypoint Script (3-4 hours)](#4-phase-2-the-setup-entrypoint-script)
5. [Phase 3: Alembic Migration Framework (4-5 hours)](#5-phase-3-alembic-migration-framework)
6. [Phase 4: System Status Endpoint (1-2 hours)](#6-phase-4-system-status-endpoint)
7. [Phase 5: Sample Data via Git LFS (2-3 hours)](#7-phase-5-sample-data-via-git-lfs)
8. [Phase 6: Cleanup, Hardening, and Docs (2-3 hours)](#8-phase-6-cleanup-hardening-and-docs)
9. [Dependency Graph](#9-dependency-graph)
10. [Risk Register](#10-risk-register)

---

## 1. Executive Summary

This plan transforms the current ~10-step manual setup into a **single-command bootstrap** (`./setup`) and establishes **safe incremental pull** via Alembic migrations. The work is broken into 6 sequential phases estimated at **14-20 hours total**.

### 1.1 Current State (Pre-Implementation)

| Dimension | Current | After |
|-----------|---------|-------|
| Developer setup commands | ~10 manual steps (README) | `./setup` (1 command) |
| Schema management | `create_all()` + ad-hoc ALTER TABLE in application code | Alembic auto-migrations, versioned in Git |
| Service startup | All 10 services always start | Compose profiles (`--profile backend`) |
| Incremental pull safety | Ad-hoc column additions (no rollback, no versioning) | Transactional migrations with rollback |
| Data strategy | DVC-only (GDrive auth required) | Three-tier: DVC → sample-data → zero-data |
| Env configuration | Single `.env.example`, no profile support | Profile-driven with `COMPOSE_PROFILES` |
| Build reproducibility | `dbgate:latest`, `uv pip install --system` | Pinned tags, optimized Docker layers |

### 1.2 Key Deliverables

| # | Deliverable | File(s) | Phase | Status |
|---|-------------|---------|-------|--------|
| 1 | Docker Compose profiles | `docker-compose.yml` (modified) | 1 | ✅ |
| 2 | Idempotent setup script | `./setup` (new) | 2 | ✅ |
| 3 | Alembic migration framework | `backend/alembic/` (new), `backend/alembic.ini` (new) | 3 | ✅ |
| 4 | Initial schema migration | `backend/alembic/versions/98edea420e0c_initial_schema.py` (new) | 3 | ✅ |
| 5 | Removed legacy migration code | `backend/src/database.py` (modified) | 3 | ✅ |
| 6 | System status endpoint | `backend/src/api/v1/endpoints/system.py` (new) | 4 | ✅ |
| 7 | Sample data directory | `sample-data/` (new) | 5 | ✅ |
| 8 | Git LFS tracking | `.gitattributes` (modified) | 5 | ✅ |
| 9 | Updated Dockerfiles | `backend/Dockerfile` (modified) | 6 | ❌ |
| 10 | Updated README | `README.md` (modified) | 6 | ❌ |

---

## 2. Pre-Implementation Checklist

Before any code changes, verify these prerequisites:

- [ ] **Docker is running** and `docker compose version` ≥ 2.x
- [ ] **Python 3.12+ is available** (for running Alembic locally during migration generation)
- [ ] **DVC remote is accessible** or sample data strategy is accepted as fallback
- [ ] **Git LFS is installed** (`git lfs version` ≥ 3.x)
- [ ] **All team members notified** about upcoming changes:
  - Migration files will appear in the repo
  - `docker compose up` behavior will change (profiles required or set `COMPOSE_PROFILES` in `.env`)
  - Legacy `Base.metadata.create_all()` will be removed
  - `./setup` replaces manual README steps

### 2.1 Branch Strategy

```bash
git checkout -b feature/portability
# Work through phases 1-6 on this branch
# Each phase committed independently for clean review
```

---

## 3. Phase 1: Docker Compose Profiles ✅

**Goal:** Allow developers to start only the services they need via `--profile` flag, reducing resource waste and startup time.

**Effort:** 2-3 hours
**File:** `docker-compose.yml` (modified), `.env.example` (modified)
**Status:** ✅ Completed on 2026-06-25

### 3.1 Profile Assignment

Each service in `docker-compose.yml` gets a `profiles:` key:

| Service | Profiles | Rationale |
|---------|----------|-----------|
| `db` | *none (always starts)* | Required by all profiles |
| `redis` | *none (always starts)* | Required by all profiles |
| `mlflow` | *none (always starts)* | Required by backend |
| `backend` | `backend`, `full` | Core API |
| `worker` | `backend`, `full` | Core async tasks |
| `celery-beat` | `backend`, `full` | Core scheduler |
| `frontend` | `frontend`, `full` | UI layer |
| `jupyter` | `analytics`, `full` | Data exploration |
| `prometheus` | `monitoring`, `full` | Metrics |
| `grafana` | `monitoring`, `full` | Dashboards |
| `dbgate` | `monitoring`, `full` | DB GUI |

### 3.2 Implementation Steps

**Step 1:** Add `profiles` to `docker-compose.yml`

```yaml
# --- Always-on services: no change ---
services:
  db:
    # ... unchanged ...

  redis:
    # ... unchanged ...

  mlflow:
    # ... unchanged ...

  # --- Add profiles: [backend, full] ---
  backend:
    profiles: ["backend", "full"]
    # ... rest unchanged ...

  worker:
    profiles: ["backend", "full"]
    # ... rest unchanged ...

  celery-beat:
    profiles: ["backend", "full"]
    # ... rest unchanged ...

  # --- Add profiles: [frontend, full] ---
  frontend:
    profiles: ["frontend", "full"]
    # ... rest unchanged ...

  # --- Add profiles: [analytics, full] ---
  jupyter:
    profiles: ["analytics", "full"]
    # ... rest unchanged ...

  # --- Add profiles: [monitoring, full] ---
  prometheus:
    profiles: ["monitoring", "full"]
    # ... rest unchanged ...

  grafana:
    profiles: ["monitoring", "full"]
    # ... rest unchanged ...

  dbgate:
    profiles: ["monitoring", "full"]
    # ... rest unchanged ...
```

**Step 2:** Add `COMPOSE_PROFILES` to `.env.example`

```bash
# Append to .env.example:
# Docker Compose profiles (comma-separated).
# Options: backend, frontend, analytics, monitoring, full
# "full" starts ALL services.
COMPOSE_PROFILES=backend
```

**Step 3:** Verify each profile works

```bash
# Test: backend-only (db, redis, mlflow, backend, worker, celery-beat)
docker compose --profile backend up -d --wait
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
# Expected: 6 services running (no frontend, no monitoring)
docker compose down

# Test: backend + frontend
docker compose --profile backend --profile frontend up -d --wait
# Expected: 7 services running
docker compose down

# Test: full (all profiles via COMPOSE_PROFILES)
COMPOSE_PROFILES=full docker compose up -d --wait
# Expected: 10 services running
docker compose down
```

### 3.3 Verification Checklist

- [x] `docker compose --profile backend up` starts exactly 6 services
- [x] `docker compose --profile full up` starts all 10 services
- [x] `docker compose up` (no flag) with `COMPOSE_PROFILES=backend` in `.env` starts backend services
- [x] `docker compose --profile monitoring --profile backend up` starts backend + monitoring (all but jupyter and frontend)
- [x] Health checks pass for all services in each profile

---

## 4. Phase 2: The `setup` Entrypoint Script ✅

**Goal:** Replace multi-step README guide with a single `./setup` command that is safe to re-run indefinitely.

**Effort:** 3-4 hours
**Files:** `./setup` (new, executable)
**Status:** ✅ Completed on 2026-06-25

### 4.1 Script Outline

```bash
#!/usr/bin/env bash
set -euo pipefail

# ─── Configuration ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env"
ENV_EXAMPLE=".env.example"
DATA_DIR="data/raw/data"
SAMPLE_DATA_DIR="sample-data"
GIT_HOOKS_PATH=".githooks"
HEALTH_URL="http://localhost:8000/health"
STATUS_URL="http://localhost:8000/api/v1/system/status"

# ─── Color helpers ──────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ─── Step 1: Environment File ───────────────────────────────────
setup_env() {
    if [ -f "$ENV_FILE" ]; then
        info "✓ .env exists, skipping creation."
    else
        info "Creating .env from .env.example..."
        cp "$ENV_EXAMPLE" "$ENV_FILE"

        # Prompt for profile if not already set
        echo ""
        echo "Which profile would you like?"
        echo "  [1] backend only    (API, workers, MLflow)"
        echo "  [2] backend + frontend"
        echo "  [3] full            (all 10 services)"
        read -rp "Enter choice [1-3]: " profile_choice
        case "$profile_choice" in
            1) prof="backend" ;;
            2) prof="backend,frontend" ;;
            3) prof="full" ;;
            *) prof="backend" ;;
        esac
        # Replace COMPOSE_PROFILES line if exists, otherwise append
        if grep -q "^COMPOSE_PROFILES=" "$ENV_FILE"; then
            sed -i "s/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=${prof}/" "$ENV_FILE"
        else
            echo "COMPOSE_PROFILES=${prof}" >> "$ENV_FILE"
        fi
        info "✓ .env created with COMPOSE_PROFILES=${prof}"
    fi

    # Source .env so COMPOSE_PROFILES is available to docker compose
    set -a; source "$ENV_FILE"; set +a
}

# ─── Step 2: Data (DVC or sample fallback) ──────────────────────
setup_data() {
    if [ -d "$DATA_DIR" ] && [ "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
        info "✓ Data directory '${DATA_DIR}' is not empty, skipping data pull."
        return
    fi

    if command -v dvc &>/dev/null && dvc remote list 2>/dev/null | grep -q gdrive; then
        info "DVC remote 'gdrive' configured. Pulling data (~4 GB)..."
        dvc pull || {
            warn "dvc pull failed. Trying sample data fallback..."
            fallback_sample_data
        }
    elif [ -d "$SAMPLE_DATA_DIR" ] && [ "$(ls -A "$SAMPLE_DATA_DIR" 2>/dev/null)" ]; then
        warn "DVC not configured. Using sample data fallback."
        fallback_sample_data
    else
        warn "No data available (DVC not configured, no sample data)."
        warn "Backend will start but data-dependent endpoints will fail."
        warn "Run 'docker compose exec backend python -m src.seeder' after obtaining data."
    fi
}

fallback_sample_data() {
    mkdir -p "$DATA_DIR"
    cp -r "$SAMPLE_DATA_DIR"/* "$DATA_DIR/" 2>/dev/null || true
    warn "Sample data copied. Model training will not work with sample data."
}

# ─── Step 3: Git Hooks ──────────────────────────────────────────
setup_hooks() {
    current_hooks_path=$(git config core.hooksPath 2>/dev/null || echo "")
    if [ "$current_hooks_path" = "$GIT_HOOKS_PATH" ]; then
        info "✓ Git hooks already configured."
    else
        info "Configuring Git hooks..."
        git config core.hooksPath "$GIT_HOOKS_PATH"
        if [ -f "${GIT_HOOKS_PATH}/pre-push" ]; then
            chmod +x "${GIT_HOOKS_PATH}/pre-push"
        fi
        info "✓ Git hooks path set to ${GIT_HOOKS_PATH}"
    fi
}

# ─── Step 4: Build and Start ────────────────────────────────────
build_and_start() {
    info "Building Docker images..."
    docker compose build

    info "Starting services..."
    docker compose up -d --wait

    info "Waiting for backend to become healthy..."
    for i in $(seq 1 60); do
        if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
            info "✓ Backend is healthy."
            break
        fi
        if [ "$i" -eq 60 ]; then
            error "Backend did not become healthy after 60 attempts."
            error "Check logs: docker compose logs backend"
            exit 1
        fi
        sleep 2
    done
}

# ─── Step 5: Verify System Status ───────────────────────────────
verify_status() {
    info "Checking system status..."
    status_json=$(curl -sf "$STATUS_URL" 2>/dev/null || echo "{}")

    # Check pending migrations
    pending=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('database',{}).get('pending_migrations',-1))" 2>/dev/null || echo "-1")
    if [ "$pending" != "0" ]; then
        warn "Database may have pending migrations (pending_migrations=${pending})."
        warn "Check: docker compose logs backend | grep alembic"
    else
        info "✓ Database schema is up to date."
    fi

    # Check data availability
    data_avail=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('dvc',{}).get('data_available',False))" 2>/dev/null || echo "False")
    if [ "$data_avail" != "True" ]; then
        warn "Data is not fully available. Some endpoints may return 503."
    else
        info "✓ Data is available."
    fi
}

# ─── Step 6: Seed Reference Data (if needed) ────────────────────
seed_if_needed() {
    # Quick check: if location table has rows, skip
    has_locations=$(docker compose exec -T db psql \
        -U "${POSTGRES_USER:-dmp_user}" \
        -d "${POSTGRES_DB:-dmp_db}" \
        -t -c "SELECT COUNT(*) FROM location;" 2>/dev/null | tr -d '[:space:]' || echo "0")

    if [ "$has_locations" != "0" ]; then
        info "✓ Database already seeded (${has_locations} locations found)."
        return
    fi

    info "Seeding reference data..."
    docker compose exec -T backend python -m src.seeder --phase reference || {
        warn "Seeding reference data failed. You can retry later with:"
        warn "  docker compose exec backend python -m src.seeder"
    }
}

# ─── Print Summary ──────────────────────────────────────────────
print_summary() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  DMP Smart City AI Platform is ready!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Services:"
    echo "    API Docs:   http://localhost:8000/docs"
    echo "    MLflow UI:  http://localhost:5000"
    echo ""
    # Only show services that are actually running
    if docker compose ps frontend 2>/dev/null | grep -q "Up"; then
        echo "    Frontend:    http://localhost:3001"
    fi
    if docker compose ps jupyter 2>/dev/null | grep -q "Up"; then
        echo "    Jupyter:     http://localhost:8888"
    fi
    if docker compose ps grafana 2>/dev/null | grep -q "Up"; then
        echo "    Grafana:     http://localhost:3003"
        echo "    Prometheus:  http://localhost:9090"
    fi
    if docker compose ps dbgate 2>/dev/null | grep -q "Up"; then
        echo "    DbGate:      http://localhost:3002"
    fi
    echo ""
    echo "  To change profiles, edit COMPOSE_PROFILES in .env"
    echo "  To add full data, configure DVC and run: dvc pull"
    echo ""
}

# ─── Main ───────────────────────────────────────────────────────
main() {
    echo "╔══════════════════════════════════════════╗"
    echo "║  DMP Project Setup (Idempotent)          ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""

    setup_env
    setup_data
    setup_hooks
    build_and_start
    verify_status
    seed_if_needed
    print_summary
}

main "$@"
```

### 4.2 Idempotency Proof Table

| Step | Guard Check | Second Run Behavior |
|------|-------------|---------------------|
| `.env` creation | `test -f .env` | Skips |
| DVC pull | `test -d data/raw/data && ls -A` non-empty | Skips |
| Git hooks | `git config core.hooksPath` matches `.githooks` | Skips |
| Docker build | Docker layer cache | Fast no-op |
| `docker compose up` | Container health | Restart only if changed |
| Seed check | `SELECT COUNT(*) FROM location` | Skips if > 0 |

### 4.3 Implementation Steps

**Step 1:** Create the script file

```bash
touch setup
chmod +x setup
```

**Step 2:** Copy the full script content above into `./setup`

**Step 3:** Test idempotency

```bash
# Test 1: Fresh clone simulation
rm -f .env
./setup
# Expected: creates .env, builds, starts, seeds

# Test 2: Immediate re-run (no-op)
./setup
# Expected: all steps skip, completes in < 30 seconds

# Test 3: After docker compose down
docker compose down
./setup
# Expected: starts containers, skips .env/data/hooks, verifies health
```

### 4.4 Verification Checklist

- [x] Fresh `rm -f .env && ./setup` creates `.env` with profile prompt
- [x] `./setup` runs again and all steps skip (completes < 30s)
- [x] After `docker compose down`, `./setup` restarts everything correctly
- [x] Script fails gracefully if Docker is not running (clear error message)
- [x] Script warns (does not error) if DVC data is unavailable
- [x] `./setup` works from any directory (uses `SCRIPT_DIR` to `cd` to project root)
- [x] Seed check correctly skips when `location` table has rows
- [x] Script handles missing Phase 4 status endpoint gracefully (Phase 2 does not depend on Phase 4)

---

## 5. Phase 3: Alembic Migration Framework ✅

**Goal:** Replace `Base.metadata.create_all()` and ad-hoc ALTER TABLE statements with versioned, transactional Alembic migrations.

**Effort:** 4-5 hours
**Files:** `backend/alembic.ini` (new), `backend/alembic/` (new), `backend/src/database.py` (modified), `docker-compose.yml` (modified)
**Status:** ✅ Completed on 2026-06-25

### 5.1 Alembic Setup

**Step 1:** Install Alembic

```bash
# If using uv (recommended)
uv add alembic

# Or pip
pip install alembic
```

**Step 2:** Create `backend/alembic.ini`

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url = %(DATABASE_URL)s

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

**Step 3:** Create `backend/alembic/env.py`

```python
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
from src.database import Base
from src import models  # noqa: F401 - Ensures all models are registered on Base.metadata

target_metadata = Base.metadata


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
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 4:** Create `backend/alembic/script.py.mako`

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

**Step 5:** Ensure `backend/src/models.py` exports `Base`

Verify that `backend/src/models.py` has:

```python
from sqlalchemy.orm import declarative_base
Base = declarative_base()
```

And that all model classes are defined in `models.py` (or are imported there). Currently the explore revealed models.py is ~447 lines with all models. Confirm ALL table models are present in this file.

**Step 6:** Generate the initial migration

```bash
cd backend
alembic revision --autogenerate -m "initial_schema"
```

This will inspect `Base.metadata` and generate `backend/alembic/versions/001_initial_schema.py`.

**Step 7:** Review the generated migration

Critical checks before committing:
- [ ] All 13+ tables are included (users, location, location_type, device, device_type, device_metric_capability, metric_type, telemetry_data, forecast_result, context_data, context_type, ai_pipeline_log, anomaly_detected_event, prediction_log, model_performance, drift_report)
- [ ] No `DROP TABLE` statements are present (initial migration should only CREATE)
- [ ] Foreign keys and indexes are correctly detected
- [ ] Enum types (e.g., `job_status`) are included if used
- [ ] JSONB columns use `sa.JSON` or `postgresql.JSONB`

**Step 8:** Modify `backend/src/database.py`

Remove legacy schema management:

```python
# BEFORE (remove these functions):
def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_user_profile_columns()
    _ensure_pipeline_log_schema()

def _ensure_user_profile_columns(): ...
def _ensure_pipeline_log_schema(): ...

# AFTER:
def init_db():
    """Verifies database connectivity only. Migrations are managed by Alembic."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        raise RuntimeError(f"Database connection failed: {e}")
```

**Step 9:** Modify `docker-compose.yml` backend command

```yaml
# BEFORE:
command: >
  sh -c "python -m src.seeders.users &&
  uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"

# AFTER:
command: >
  sh -c "alembic upgrade head &&
  python -m src.seeders.users &&
  uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"
```

**Step 10:** Legacy columns handled by initial migration

The columns that were previously maintained by `_ensure_user_profile_columns()` (contact_number, status, assigned_site_ids, is_global_admin) and `_ensure_pipeline_log_schema()` (celery_task_id, 'Cancelled' job_status) are already present in the SQLAlchemy model definitions in `models.py`. The initial migration captures all of them automatically.

No separate legacy migration files are needed. For existing developer databases that already have all tables (created by the old `create_all()` + `_ensure_*()` code), run `alembic stamp head` to mark the current state:

```bash
docker compose exec backend alembic stamp head
```

This creates the `alembic_version` table and records the head revision without applying any DDL changes.

> **Why this approach is safe:** The old `create_all()` created tables matching the model definitions, and the `_ensure_*()` functions backfilled any missing columns with the exact same schema. The initial migration creates the same schema. Since existing databases already match, stamping (rather than running the migration) is correct.

### 5.2 Testing Alembic

**Step 11:** Test on a fresh database

```bash
# Start a fresh Postgres (no existing data)
docker compose down -v  # WARNING: destroys all data
docker compose --profile backend up -d db
sleep 5

# Run migrations manually
cd backend
DATABASE_URL=postgresql://dmp_user:dmp_password@localhost:5432/dmp_db \
  alembic upgrade head

# Verify tables exist
docker compose exec db psql -U dmp_user -d dmp_db -c "\dt"
```

**Step 12:** Test incremental migration

```bash
# Apply initial migration
DATABASE_URL=postgresql://... alembic upgrade 001_initial_schema

# Create a new migration (simulate schema change)
# ... (add a test column to a model)
alembic revision --autogenerate -m "test_add_column"

# Apply the new migration
DATABASE_URL=postgresql://... alembic upgrade head

# Verify column exists
docker compose exec db psql -U dmp_user -d dmp_db \
  -c "SELECT column_name FROM information_schema.columns WHERE table_name='users';"

# Rollback
DATABASE_URL=postgresql://... alembic downgrade -1

# Verify column is gone
```

**Step 13:** Test migration failure rollback

```bash
# Create a deliberately broken migration
cat > backend/alembic/versions/999_test_failure.py << 'EOF'
"""test failure
"""
revision = '999'
down_revision = '001_initial_schema'

def upgrade():
    op.execute("SELECT 1/0")  # Will fail

def downgrade():
    pass
EOF

# Run migration (should fail)
DATABASE_URL=... alembic upgrade head
# Expected: ERROR, migration failed, database left in last good state

# Clean up
rm backend/alembic/versions/999_test_failure.py
```

### 5.3 Verification Checklist

- [x] `alembic upgrade head` creates all 18 tables on a fresh database
- [x] Running `alembic upgrade head` twice is idempotent (no errors)
- [x] `alembic revision --autogenerate` correctly detects model changes
- [x] `alembic downgrade -1` reverts the last migration (tables dropped)
- [ ] A broken migration rolls back and leaves the database untouched (PostgreSQL ENUMs persist across table drops; full cleanup requires volume wipe)
- [x] Docker Compose backend command includes `alembic upgrade head` with stamp guard for existing databases
- [x] `init_db()` in database.py no longer calls `create_all()` or `_ensure_*`
- [x] All legacy columns (contact_number, status, assigned_site_ids, is_global_admin, celery_task_id) are captured in the initial migration directly from model definitions

> **Note on legacy migration files:** The initial migration captures ALL current columns from the model definitions (including the "legacy" columns that were previously added via `_ensure_user_profile_columns()` and `_ensure_pipeline_log_schema()`). Separate legacy migration files are unnecessary because the initial migration covers everything. Existing databases should use `alembic stamp head` to mark their current state without re-running migration 001.

---

## 6. Phase 4: System Status Endpoint ✅

**Goal:** Provide a `/api/v1/system/status` endpoint that the `setup` script can poll to verify database migration state and data availability.

**Effort:** 1-2 hours
**Files:** `backend/src/api/v1/endpoints/system.py` (new), `backend/src/api/v1/router.py` (modified)
**Status:** ✅ Completed on 2026-06-25

### 6.1 Endpoint Specification

```python
# backend/src/api/v1/endpoints/system.py

import os
import subprocess
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import inspect, text

from src.database import engine, _ALEMBIC_INI_PATH

router = APIRouter(prefix="/system", tags=["system"])


def _get_alembic_status():
    """Query alembic_version table to determine migration state."""
    try:
        with engine.connect() as conn:
            # Check if alembic_version table exists
            inspector = inspect(engine)
            if "alembic_version" not in inspector.get_table_names():
                return {
                    "current_revision": None,
                    "head_revision": None,
                    "pending_migrations": -1,
                }

            # Get current revision
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            current = result.scalar()

            # Get head revision (from most recent migration file)
            head = None
            versions_dir = os.path.join(
                os.path.dirname(_ALEMBIC_INI_PATH), "alembic", "versions"
            )
            if os.path.isdir(versions_dir):
                migration_files = sorted(
                    [f for f in os.listdir(versions_dir) if f.endswith(".py") and f != "__init__.py"],
                    reverse=True,
                )
                if migration_files:
                    # Parse revision ID from filename: 001_description.py -> 001
                    head = migration_files[0].split("_")[0]

            # Compute pending migrations
            pending = -1
            if current and head:
                pending = 0 if current == head else 1

            return {
                "current_revision": current,
                "head_revision": head,
                "pending_migrations": pending,
            }
    except Exception as e:
        return {
            "current_revision": None,
            "head_revision": None,
            "pending_migrations": -1,
            "error": str(e),
        }


def _get_dvc_status():
    """Check if DVC-tracked data is available."""
    data_path = os.getenv("DATA_PATH", "/app/data/raw/data")
    data_available = False
    last_pull = None

    if os.path.isdir(data_path) and os.listdir(data_path):
        data_available = True
        # Try to get last modification time
        try:
            latest = max(
                os.path.getmtime(os.path.join(data_path, f))
                for f in os.listdir(data_path)
            )
            last_pull = datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            pass

    return {
        "data_available": data_available,
        "data_path": data_path,
        "last_pull": last_pull,
    }


@router.get("/status")
def system_status():
    """Return system health and configuration status.

    Used by the setup script to verify deployment readiness.
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
```

### 6.2 Router Registration

In `backend/src/api/v1/router.py`, add:

```python
from src.api.v1.endpoints import system

api_router.include_router(system.router, tags=["system"])
```

### 6.3 Verification Checklist

- [x] `GET /api/v1/system/status` returns 200 with correct JSON structure
- [x] `database.connected` is `true` when DB is up
- [x] `database.pending_migrations` reports correct revision mismatch
- [x] `database.pending_migrations` is `0` after `alembic upgrade head`
- [x] `dvc.data_available` reflects actual data directory state
- [x] Endpoint works when DVC data is absent (returns `data_available: false`)
- [x] `setup` script correctly parses the response (gracefully handles missing endpoint)

---

## 7. Phase 5: Sample Data via Git LFS ✅

**Goal:** Provide a lightweight data fallback (~50-100 MB) for developers without DVC/GDrive access, so the API starts and basic endpoints work.

**Effort:** 2-3 hours
**Files:** `sample-data/` (new), `.gitattributes` (modified), `./setup` (modified)
**Status:** ✅ Completed on 2026-06-25

### 7.1 Design Decisions

| Decision | Rationale |
|----------|-----------|
| Git LFS (not plain Git) | Sample CSVs can be 50-100 MB total; Git LFS avoids bloating the repo |
| Representative subset | First 1000 rows per CSV -- enough to test all API endpoints |
| No model training with sample data | Training requires the full 4 GB dataset; clear error messages |
| Separate `sample-data/` directory | Clean separation from DVC-tracked `data/` |

### 7.2 Implementation Steps

**Step 1:** Initialize Git LFS

```bash
git lfs install
git lfs track "sample-data/**/*.csv"
```

**Step 2:** Update `.gitattributes`

Add these lines:

```
# Git LFS for sample data
sample-data/**/*.csv filter=lfs diff=lfs merge=lfs -text
```

**Step 3:** Create sample data directory structure

```bash
mkdir -p sample-data/data/metadata
mkdir -p sample-data/data/meters/kaggle
mkdir -p sample-data/data/weather
```

**Step 4:** Generate sample data subsets

```bash
# For each CSV in the full data directory, extract first 1000 rows
# Example (adjust paths based on actual data structure):

# Metadata (small enough to copy in full)
cp data/raw/data/metadata/metadata.csv sample-data/data/metadata/

# Meter data - first 1000 rows
head -1001 data/raw/data/meters/kaggle/electricity.csv > sample-data/data/meters/kaggle/electricity.csv
head -1001 data/raw/data/meters/kaggle/water.csv > sample-data/data/meters/kaggle/water.csv

# Weather data - first 1000 rows
head -1001 data/raw/data/weather/weather.csv > sample-data/data/weather/weather.csv
```

**Step 5:** Commit sample data

```bash
git add sample-data/ .gitattributes
git commit -m "feat: add sample data via Git LFS for DVC fallback"
```

**Step 6:** Update `setup` script to use sample data

The `fallback_sample_data()` function is already in the setup script from Phase 2. Ensure the path mapping is correct:

```bash
fallback_sample_data() {
    mkdir -p "$DATA_DIR"
    # Copy sample data maintaining directory structure
    cp -r "$SAMPLE_DATA_DIR"/* "$DATA_DIR/" 2>/dev/null || true
    warn "Sample data copied. Model training will not work with sample data."
    warn "To obtain the full dataset: install DVC and run 'dvc pull'"
}
```

### 7.3 Data-Dependent Endpoint Responses

When only sample data is available (no full DVC dataset), endpoints that depend on large training data should return clear 503 errors:

| Endpoint | Without full data | Behavior |
|----------|------------------|----------|
| `POST /training/` | 503 `DATA_NOT_AVAILABLE` | Clear message: "Training requires the full dataset via DVC" |
| `POST /training/validate` | 200 with `data_available: false` | Reports what's missing |
| `POST /forecast/` | 503 `DATA_NOT_AVAILABLE` | Clear message |
| `POST /prediction/scenario` | 503 `DATA_NOT_AVAILABLE` | Clear message |
| `GET /anomaly/*` | 200 with empty results | Graceful degradation |
| `GET /telemetry/*` | 200 with sample data | Works with available data |
| `GET /metadata/*` | 200 | Full metadata always works |

**Note:** The 503 `DATA_NOT_AVAILABLE` response for training/forecast endpoints requires adding a guard check in those endpoint handlers. This can be done in a follow-up; the portability plan focuses on the setup infrastructure.

### 7.4 Verification Checklist

- [x] `git lfs track` outputs show `sample-data/**/*.csv` is tracked
- [x] `sample-data/` directory contains representative data files (metadata, 8 cleaned meter CSVs, weather)
- [x] Total `sample-data/` size is 20 MB (< 100 MB)
- [x] `./setup` without DVC copies sample data to `data/raw/data/` (via `fallback_sample_data()`)
- [ ] Backend starts and serves metadata/telemetry endpoints (requires running services)
- [ ] Training/forecast endpoints return clear error messages (follow-up work)
- [ ] Cloning the repo (with Git LFS) pulls sample data automatically

---

## 8. Phase 6: Cleanup, Hardening, and Docs

**Goal:** Remove technical debt identified in the portability gap analysis, harden Dockerfiles, and update documentation.

**Effort:** 2-3 hours
**Files:** `backend/Dockerfile` (modified), `docker-compose.yml` (modified), `README.md` (modified), `docs/architecture/portability.md` (updated status)

### 8.1 Dockerfile Hardening

**Gap #8 Fix — Optimize layer caching:**

```dockerfile
# backend/Dockerfile (MODIFIED)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm

WORKDIR /app

# Copy dependency files first for better layer caching
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
```

**Gap #10 Fix — Pin dbgate version:**

```yaml
# docker-compose.yml (MODIFIED)
dbgate:
  image: dbgate/dbgate:6.3.0  # Pinned from :latest
```

### 8.2 Remove Dead Code

**Gap #1 Fix — Legacy migration code removal:**

In `backend/src/database.py`:
- [ ] Remove `_ensure_user_profile_columns()` function
- [ ] Remove `_ensure_pipeline_log_schema()` function
- [ ] Remove `Base.metadata.create_all()` call from `init_db()`

These are replaced by Alembic migration files from Phase 3.

### 8.3 README Rewrite

Replace the multi-step guide with:

```markdown
## Quick Start

### Prerequisites
- Docker and Docker Compose v2.x
- Python 3.12+ (for DVC support, optional)
- Git LFS (for sample data, installed automatically by Git)

### One-Command Setup

```bash
git clone https://github.com/stardust-zip/dmp-project.git
cd dmp-project
./setup
```

That's it. The setup script is **idempotent** — safe to run repeatedly.
After pulling new code, just run `./setup` again. Your existing data is preserved.

### Profiles

| Command | Starts | Use Case |
|---------|--------|----------|
| `./setup` (default: backend) | db, redis, mlflow, backend, worker, celery-beat | API development |
| `COMPOSE_PROFILES=backend,frontend ./setup` | + frontend | Full-stack development |
| `COMPOSE_PROFILES=full ./setup` | All 10 services | Demos, production-like testing |

Or set `COMPOSE_PROFILES` in your `.env` file once.

### Data Options

| Mode | Setup | Size | Capabilities |
|------|-------|------|--------------|
| **Full (DVC)** | `dvc pull` (requires GDrive access) | ~4 GB | Training, forecasting, all endpoints |
| **Sample (LFS)** | Automatic fallback | ~50 MB | API testing, metadata, telemetry queries |
| **Zero-data** | No action needed | 0 MB | API starts, data endpoints return 503 |
```

### 8.4 Update portability.md Status

In `docs/architecture/portability.md`, change:

```markdown
**Status:** Draft
**Version:** 0.1.0
```

to:

```markdown
**Status:** Implemented
**Version:** 1.0.0
**Last Updated:** 2026-06-25
**Implementation Plan:** [implementation-plan.md](./implementation-plan.md)
```

(Do this only after all phases are complete.)

### 8.5 Verification Checklist

- [ ] `docker compose build` uses layer cache (second build < 10 seconds)
- [ ] `dbgate:latest` replaced with pinned version in docker-compose.yml
- [ ] `database.py` contains no `create_all()`, no `_ensure_*()` functions
- [ ] `init_db()` is a simple `SELECT 1` health check
- [ ] `README.md` quick-start section is <= 30 lines
- [ ] Running `./setup` from the README instructions works end-to-end
- [ ] `.env.example` includes `COMPOSE_PROFILES`

---

## 9. Dependency Graph

```mermaid
graph TD
    P1[Phase 1: Docker Compose Profiles] --> P2[Phase 2: setup Script]
    P1 --> P3[Phase 3: Alembic Migrations]
    P3 --> P4[Phase 4: System Status Endpoint]
    P2 --> P4
    P2 --> P5[Phase 5: Sample Data + Git LFS]
    P1 --> P6[Phase 6: Cleanup and Docs]
    P2 --> P6
    P3 --> P6
    P4 --> P6
    P5 --> P6
```

**Execution order:** Phases 1, 3, and 5 can partially overlap, but 2 depends on 1's profiles, 4 depends on 3's Alembic setup, and 6 depends on everything.

**Recommended sequential order:** 1 → 2 → 3 → 4 → 5 → 6

---

## 10. Risk Register

| # | Risk | Probability | Impact | Mitigation |
|---|------|-------------|--------|------------|
| 1 | **Alembic auto-generation misses tables/columns** during initial migration | Medium | High — data loss on fresh clone | Manually review generated migration against current `models.py`. Compare with `Base.metadata.tables.keys()`. Test on fresh database. |
| 2 | **Existing developer databases have no `alembic_version` table** | High | Medium — first `alembic upgrade head` tries to CREATE existing tables | Use `alembic stamp head` to mark existing DB as "already migrated" without running migrations. Document for team. |
| 3 | **DVC remote becomes unavailable** during Phase 5 testing | Low | Low — blocks sample data verification only | Sample data generation does not depend on DVC remote (uses local data). |
| 4 | **`./setup` script has a bug that destroys data** | Low | Critical — developer loses seeded data | Script is read-only except for `cp` of sample data (only on empty `data/raw/data/`). Never runs destructive commands. Review thoroughly. |
| 5 | **Docker Compose profile change breaks CI/CD** | Medium | Medium — tests fail | Update CI/CD to use explicit `--profile` flags. Add to `.github/workflows/` if CI exists. |
| 6 | **Team members run `./setup` before pulling migration files** | Medium | Low — database out of sync | Alembic fails gracefully with clear error. Running `git pull && ./setup` resolves it. |
| 7 | **`uv sync` vs `uv pip install --system` Dockerfile change** | Low | Medium — build breaks | Test Docker build after changing to `uv sync`. Verify virtual env path is correct. |

### 10.1 Risk #2 Detail: Stamping Existing Databases

When Phase 3 is deployed, developer machines already have a Postgres volume with all tables created by `Base.metadata.create_all()`. The `alembic_version` table doesn't exist.

**Mitigation procedure:**

```bash
# On each developer's machine after pulling Phase 3 code:
docker compose exec backend alembic stamp head
# This creates the alembic_version table and sets it to the head revision
# WITHOUT running any migrations (since tables already exist)
```

Add a guard to the backend startup command:

```bash
# In docker-compose.yml backend command:
sh -c "
  if python -c 'from sqlalchemy import inspect; from src.database import engine; print(\"users\" in inspect(engine).get_table_names())' | grep -q True; then
    if ! python -c 'from sqlalchemy import inspect; from src.database import engine; print(\"alembic_version\" in inspect(engine).get_table_names())' | grep -q True; then
      echo 'Existing database detected without alembic_version. Stamping head...'
      alembic stamp head
    fi
  fi
  alembic upgrade head &&
  python -m src.seeders.users &&
  uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
"
```

---

## Appendix A: Total File Inventory

| File | Phase | Action | Purpose | Status |
|------|-------|--------|---------|--------|
| `docker-compose.yml` | 1, 3, 6 | Modify | Add `profiles:`, add `alembic upgrade head` to backend command, pin `dbgate` version | ✅ Phase 1 & 3 |
| `.env.example` | 1 | Modify | Add `COMPOSE_PROFILES=backend` | ✅ |
| `./setup` | 2 | **New** | Idempotent entrypoint script | ✅ |
| `./setup` | 5 | Already implements | `fallback_sample_data()` copies sample-data/ → data/raw/data/ | ✅ (Phase 2) |
| `backend/alembic.ini` | 3 | **New** | Alembic configuration | ✅ |
| `backend/alembic/env.py` | 3 | **New** | Alembic environment (auto-detect models) | ✅ |
| `backend/alembic/script.py.mako` | 3 | **New** | Migration template | ✅ |
| `backend/alembic/versions/98edea420e0c_initial_schema.py` | 3 | **New** | Auto-generated initial migration (18 tables) | ✅ |
| `backend/src/database.py` | 3, 6 | Modify | Remove `create_all()`, `_ensure_*()`; replace with `SELECT 1` health check | ✅ |
| `backend/src/api/v1/endpoints/system.py` | 4 | **New** | System status endpoint | ✅ |
| `backend/src/api/v1/router.py` | 4 | Modify | Register system router | ✅ |
| `sample-data/` | 5 | **New** | Sample data directory (Git LFS tracked) | ✅ |
| `.gitattributes` | 5 | Modify | Add Git LFS patterns | ✅ |
| `backend/Dockerfile` | 6 | Modify | Replace `uv pip install --system` with `uv sync --frozen` |
| `README.md` | 6 | Modify | Replace multi-step guide with `./setup` + profile docs |
| `docs/architecture/portability.md` | 6 | Modify | Update status to "Implemented" |

---

## Appendix B: Rollback Plan

If Phase 3 (Alembic) causes issues in production or team workflows:

1. **Revert `database.py`** to original `init_db()` with `create_all()` + `_ensure_*()`
2. **Revert `docker-compose.yml`** backend command to remove `alembic upgrade head`
3. **No data is lost** — Alembic only adds the `alembic_version` table; existing data is untouched
4. **Downgrade any applied migrations:** `alembic downgrade base` then remove migration files

---

## Appendix C: Estimated Timeline

| Phase | Tasks | Effort | Dependencies |
|-------|-------|--------|--------------|
| Phase 1 | Docker Compose profiles | 2-3 hours | None |
| Phase 2 | `./setup` script | 3-4 hours | Phase 1 |
| Phase 3 | Alembic migrations | 4-5 hours | None (can run parallel with P1/P2, but P2 integration depends on P3 backend command) |
| Phase 4 | System status endpoint | 1-2 hours | Phase 3 |
| Phase 5 | Sample data + Git LFS | 2-3 hours | None (independent) |
| Phase 6 | Cleanup, hardening, docs | 2-3 hours | Phases 1-5 |
| **Total** | | **14-20 hours** | |

**Recommended sprint allocation:** 3-4 days for a single developer, or 2 days with parallel work on Phases 3 and 5.
