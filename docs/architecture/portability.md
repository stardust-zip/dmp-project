# Architecture: Service Topology & Portability Design

This document describes how the DMP platform services are wired together and
the design decisions that make the stack portable across machines.

---

## Service Graph

```
┌─────────────────────────────────────────────────────────────────┐
│  Host machine (all traffic via docker compose network)          │
│                                                                 │
│   ┌──────────┐    ┌──────────┐    ┌──────────────────────────┐ │
│   │  frontend│    │  jupyter │    │     monitoring stack     │ │
│   │ :3001    │    │  :8888   │    │  grafana:3003            │ │
│   └────┬─────┘    └────┬─────┘    │  prometheus:9090         │ │
│        │               │          │  dbgate:3002             │ │
│        ▼               │          └────────────┬─────────────┘ │
│   ┌──────────┐          │                       │               │
│   │  backend │◄─────────┘                       │               │
│   │  :8000   │                                  │               │
│   └──┬───┬───┘                                  │               │
│      │   │                                      │               │
│      │   ▼                                      │               │
│      │  ┌──────────┐   ┌──────────┐             │               │
│      │  │  worker  │   │  beat    │             │               │
│      │  │ (celery) │   │ (celery) │             │               │
│      │  └────┬─────┘   └────┬─────┘             │               │
│      │       │              │                   │               │
│      ▼       ▼              ▼                   ▼               │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                    Core services (always-on)             │  │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐ │  │
│   │  │ PostgreSQL │  │   Redis    │  │       MLflow       │ │  │
│   │  │ :5432      │  │ :6379      │  │       :5000        │ │  │
│   │  └────────────┘  └────────────┘  └────────────────────┘ │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Service Responsibilities

| Service | Image / Build | Always-on? | Responsibility |
|---|---|---|---|
| `db` | `postgres:17-alpine` | ✅ | Primary data store for app data and MLflow tracking metadata |
| `redis` | `redis:8.8-alpine` | ✅ | Celery broker + result backend |
| `mlflow` | `mlflow/Dockerfile` | ✅ | Experiment tracking UI + model registry; uses `db` as backend store and a named volume for artifacts |
| `backend` | `backend/Dockerfile` | profile: `backend` | FastAPI REST API; runs Alembic migrations on every startup via `entrypoint.sh` |
| `worker` | same image as backend | profile: `backend` | Celery worker; executes training and forecasting tasks dispatched by the API |
| `celery-beat` | same image as backend | profile: `backend` | Celery beat scheduler; triggers periodic tasks (e.g. drift checks) |
| `frontend` | `frontend/Dockerfile` | profile: `frontend` | Next.js dashboard; proxies API calls through `/api/backend` → `http://backend:8000` |
| `jupyter` | `uv:python3.11-bookworm` | profile: `analytics` | JupyterLab; mounts the entire repo, connects to MLflow and Postgres |
| `prometheus` | `prom/prometheus` | profile: `monitoring` | Scrapes `/metrics` from backend |
| `grafana` | `grafana/grafana` | profile: `monitoring` | Dashboards backed by Prometheus |
| `dbgate` | `dbgate/dbgate:6.3.0` | profile: `monitoring` | Web-based Postgres GUI |

**Why `db`, `redis`, and `mlflow` have no profile:** Every other service
depends on one or more of these three.  Requiring a profile flag for them
would mean every combination of profile flags would also need to include
`--profile core`.  They start unconditionally so that any profile combination
works without thinking about it.

---

## Persistent Data

All stateful data lives in **Docker named volumes** — never in bind-mounted
host directories.  This means `docker compose down` (without `-v`) never
destroys data, and `./setup` is safe to re-run on a machine with existing data.

| Volume | Owned by | Contains |
|---|---|---|
| `pgdata` | `db` | All PostgreSQL tables: app schema + MLflow tracking schema |
| `mlflow_artifacts` | `mlflow`, `backend`, `worker` | Trained model files, plots, and other artifacts |
| `redis_data` | `redis` | Celery task queue state |
| `grafana_data` | `grafana` | Dashboard definitions and user settings |
| `prom_data` | `prometheus` | 15-day metrics TSDB |
| `dbgate_data` | `dbgate` | Saved connections |
| `frontend_node_modules` | `frontend` | Node dependency cache (avoids re-install on rebuild) |

---

## Database Schema Ownership

Two separate systems share the same PostgreSQL database (`dmp_db`) but manage
their schemas independently:

| System | Version table | Tables |
|---|---|---|
| DMP backend (Alembic) | `dmp_alembic_version` | All app tables (`location`, `device`, `telemetry_data`, etc.) |
| MLflow (internal Alembic) | `alembic_version` | `experiments`, `runs`, `metrics`, `params`, etc. |

Using a custom `version_table = dmp_alembic_version` in `backend/alembic.ini`
is what prevents the two migration systems from colliding.

---

## Migration Safety on Startup

`backend/entrypoint.sh` runs before uvicorn and handles every database state
a developer could encounter when pulling new code:

| Database state | Detection | Action |
|---|---|---|
| Fresh (no tables) | No app tables found | `alembic upgrade head` creates everything |
| Already up to date | Version stamp matches head | `alembic upgrade head` is a no-op |
| Pre-Alembic tables (no version table) | App tables exist, `dmp_alembic_version` absent | `alembic stamp head` then no-op upgrade |
| Orphaned version stamp | Version number not in migration files | Delete stale stamp → stamp or upgrade as above |
| Orphaned PostgreSQL enum types | `alembic upgrade head` output contains `already exists` | Drop stale enums, retry upgrade once |

The detection logic uses `Base.metadata.tables.keys()` (derived from
`src/models.py`) rather than a hard-coded list, so it stays correct as the
schema evolves.

---

## Data Strategy

The platform supports three data states, ordered by availability:

```
DVC full dataset (~4 GB, GDrive)
  └─ if unavailable → Git LFS sample data (~20 MB, in-repo)
       └─ if unavailable → zero-data mode (API starts, data endpoints return 503)
```

The `./setup` script walks this fallback chain automatically.  Sample data
covers all API endpoints except model training and forecasting (which require
the full historical dataset).
