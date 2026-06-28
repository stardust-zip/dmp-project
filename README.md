# DMP Smart City AI Platform — Developer Guide

## Quick Start

### Prerequisites

Verify you have the required tools installed:

```bash
docker --version          # needs v27+
docker compose version    # needs v2+
git lfs version           # needs v3+
```

- **Docker & Docker Compose v2.x** — the entire stack runs in containers
- **Python 3.12+** — only needed for DVC; `uv` is used inside containers automatically
- **Git LFS 3.x** — pulls the sample data stored in `sample-data/`

### One-Command Setup

```bash
git clone https://github.com/stardust-zip/dmp-project.git
cd dmp-project
./setup
```

That's it. The `./setup` script at the project root is **idempotent** — safe to run
repeatedly. After pulling new code, just run `./setup` again. Your existing data
is preserved.  If `./setup` is not executable, run `chmod +x setup` once.

**Behind the scenes:** `./setup` creates your `.env` (with an interactive profile
selector), pulls DVC data (or falls back to Git LFS sample data), configures
Git hooks, builds Docker images, starts services, runs Alembic migrations,
seeds reference data, and prints URLs for all running services.

### Profiles

Docker Compose profiles let you start only the services you need.
Pick one when running `./setup` for the first time, or set it permanently
in `.env`:

| Method | Example |
|--------|---------|
| Interactive prompt | `./setup` (choose 1–5 when asked) |
| Environment variable | `COMPOSE_PROFILES=full ./setup` |
| Permanent (`.env`) | `COMPOSE_PROFILES=backend,frontend` |

| Profile | Starts | Use case |
|---------|--------|----------|
| `backend` (default) | db, redis, mlflow, backend, worker, celery-beat | API development |
| `backend,frontend` | + frontend dashboard | Full-stack development |
| `full` | All 10 services | Demos, production-like testing |
| `monitoring` | Prometheus, Grafana, DbGate | Observability only |
| `analytics` | JupyterLab | Data exploration |

> **Profile precedence:** A `COMPOSE_PROFILES=...` value set in the calling
> shell overrides whatever is in `.env`.  Running `./setup` later honours
> whatever is in `.env` (since no shell override is present).

### Data Options

| Mode | Setup | Size | Capabilities |
|------|-------|------|--------------|
| **Full (DVC)** | `dvc pull` (requires GDrive access) | ~4 GB | Training, forecasting, all endpoints |
| **Sample (LFS)** | Automatic fallback in `./setup` | ~20 MB | API testing, metadata, telemetry queries |
| **Zero-data** | No action needed | 0 MB | API starts, data endpoints return errors |

---

## Service Map

Once the stack is running, you can access the tools at these URLs (availability
depends on the profile you selected):

| Service | URL | Profile |
|---------|-----|---------|
| FastAPI (Swagger UI) | http://localhost:8000/docs | backend |
| MLflow (Model Tracking) | http://localhost:5000 | always |
| Frontend Dashboard | http://localhost:3001 | frontend |
| JupyterLab (AI Workspace) | http://localhost:8888 | analytics |
| Grafana (Monitoring) | http://localhost:3003 | monitoring |
| Prometheus (Metrics) | http://localhost:9090 | monitoring |
| DbGate (Database GUI) | http://localhost:3002 | monitoring |

### Demo Credentials

The `./setup` script seeds 25 demo users.  Use these to log in:

| Role | Email | Password |
|------|-------|----------|
| Global Admin | `admin@dmp.com` | `demo123` |
| Site Admin | `siteadmin@dmp.com` | `demo123` |
| Operator | `operator@dmp.com` | `demo123` |
| AI Engineer | `ai@dmp.com` | `demo123` |

---

## Seeding Data

The `./setup` script seeds reference data (locations, devices, users) automatically.
For telemetry and weather data, use the seeder directly:

```bash
# Quick seed: reference data + 1,000 telemetry rows per metric
docker compose exec backend python -m src.seeder

# Full seed: entire historical dataset
docker compose exec backend python -m src.seeder --full

# Selective seeding
docker compose exec backend python -m src.seeder --phase reference
docker compose exec backend python -m src.seeder --phase telemetry --metrics electricity,water
docker compose exec backend python -m src.seeder --phase weather
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--phase` | `all` | `reference` / `telemetry` / `weather` / `all` |
| `--metrics` | all 8 | Comma-separated: `electricity,water,gas` |
| `--limit` | 1,000 | Dev-mode row cap per metric |
| `--full` | off | Overrides `--limit` — loads everything |

---

## Making Schema Changes

This project uses **Alembic** for database migrations (replaces the old
`Base.metadata.create_all()` approach). The `init_db()` function now only
verifies database connectivity — schema changes are always managed through
migration files.

1. **Modify the model** in `backend/src/models.py`.
2. **Generate a migration** (requires the stack to be running):
   ```bash
   docker compose exec backend alembic revision --autogenerate -m "describe_your_change"
   ```
3. **Review** the generated file in `backend/alembic/versions/`.
4. **Apply it:**
   ```bash
   docker compose exec backend alembic upgrade head
   ```
5. **Commit** both the model change and the migration file.

> **For existing databases** that were created before Alembic was introduced,
> the backend auto-detects this on startup and runs `alembic stamp head`
> to mark the current state without re-applying migrations. No manual
> intervention is needed.

---

## DVC (Full Dataset)

The full dataset (~4 GB) is managed via DVC with a Google Drive remote.
Without it, `./setup` automatically falls back to the Git LFS sample data
(see [Data Options](#data-options)).

```bash
# The GDrive OAuth app credentials are already committed in .dvc/config.
# Just run dvc pull — it will open a browser tab to authenticate your
# Google account the first time.
dvc pull
```

After `dvc pull`, re-run `./setup` to restart services with the full dataset.

---

## Example Workflows

1. Navigate to **JupyterLab** at `localhost:8888` (requires `analytics` profile).
2. The Jupyter container automatically connects to Postgres and MLflow.
3. When tracking models, use standard MLflow commands — results appear in the
   MLflow UI at `localhost:5000`.
4. If you engineer new datasets, track them with DVC:
   ```bash
   dvc add data/new_dataset.csv
   dvc push
   git add data/new_dataset.csv.dvc
   git commit -m "data: added new dataset"
   ```

---

## Project Layout

```
dmp-project/
├── backend/
│   ├── alembic/            # Migration scripts (versioned schema history)
│   │   └── versions/       # One file per migration — never edit by hand
│   ├── src/
│   │   ├── api/v1/
│   │   │   ├── endpoints/  # One file per domain: auth, telemetry, forecast, …
│   │   │   ├── deps.py     # FastAPI dependency injection (auth, DB session)
│   │   │   └── router.py   # Mounts all endpoint routers
│   │   ├── core/
│   │   │   ├── config.py   # Pydantic Settings — all env vars read here
│   │   │   └── security.py # JWT encode/decode, password hashing
│   │   ├── ml/             # ML inference helpers called by endpoints
│   │   ├── seeders/        # Data seeding scripts (users, metadata, telemetry)
│   │   ├── models.py       # SQLAlchemy ORM models (single source of truth)
│   │   ├── schemas.py      # Pydantic request/response schemas
│   │   ├── database.py     # Engine + session factory
│   │   ├── tasks.py        # Celery task definitions (training, forecasting)
│   │   └── main.py         # FastAPI app factory + middleware
│   ├── tests/              # pytest suite (TestClient, no live DB required)
│   ├── alembic.ini         # Alembic config (version_table = dmp_alembic_version)
│   ├── Dockerfile
│   └── entrypoint.sh       # Migration-safe startup (stamp/upgrade/retry logic)
├── forecasting_module/     # Pure-Python ML pipeline (importable by Jupyter + backend)
├── frontend/               # Next.js dashboard
├── grafana/                # Grafana dashboard provisioning configs
├── sample-data/            # Git LFS — representative CSV subset (~20 MB)
├── docs/architecture/      # Architecture decision records
├── docker-compose.yml      # All services + profiles
├── .env.example            # Env var template (copy → .env)
├── pyproject.toml          # Python deps (uv) + tool config
└── setup                   # Idempotent one-command bootstrap
```

---

## Development Workflow

`backend/src/` is bind-mounted into the container and uvicorn runs with
`--reload`, so **Python changes take effect immediately** without a rebuild.

```bash
# After pulling new code (migrations, deps, or config changes):
./setup

# Day-to-day: just edit files under backend/src/ — the running container
# picks up changes automatically via uvicorn --reload.

# If you change pyproject.toml (new dependency):
docker compose build backend worker celery-beat
docker compose up -d backend worker celery-beat

# Tail live logs while working:
docker compose logs -f backend
docker compose logs -f worker

# Open an interactive shell inside the backend container:
docker compose exec backend bash

# Run a one-off Python expression in the app context:
docker compose exec backend python -c "from src.database import engine; print(engine.url)"
```

### Adding a new API endpoint

1. Create (or add to) a file in `backend/src/api/v1/endpoints/`.
2. Define a `router = APIRouter(prefix="/your-resource", tags=["your-resource"])`.
3. Register it in `backend/src/api/v1/router.py`.
4. Test immediately at `http://localhost:8000/docs` — no restart needed.

---

## Running Tests

Tests use FastAPI's `TestClient` and dependency overrides — **no live database
required**.

```bash
# Run the full test suite inside the backend container:
docker compose exec backend uv run pytest backend/tests/ -v

# Run a specific test file:
docker compose exec backend uv run pytest backend/tests/test_users.py -v

# Run with coverage:
docker compose exec backend uv run pytest backend/tests/ --cov=src --cov-report=term-missing
```

The pre-push hook (`.githooks/pre-push`) runs `ruff check` automatically.
To run the linter manually:

```bash
docker compose exec backend uv run ruff check backend/src/
```

---

## Environment Variables

All variables are read through `backend/src/core/config.py` via Pydantic Settings.
The `.env` file is the authoritative source; `docker-compose.yml` overrides
connection strings inside containers (e.g. `@localhost` → `@db`).

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_USER` | `dmp_user` | PostgreSQL credentials (shared by DB, MLflow, backend) |
| `POSTGRES_PASSWORD` | `dmp_password` | |
| `POSTGRES_DB` | `dmp_db` | |
| `DATABASE_URL` | `postgresql://…@localhost:5432/dmp_db` | Host-side URL; containers use `@db:5432` |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` | Set automatically by docker-compose |
| `SECRET_KEY` | `demo_super_secret_key…` | **Change this in any non-local environment** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` (7 days) | JWT lifetime |
| `COMPOSE_PROFILES` | `backend` | Which Docker Compose profile to activate |
| `GRAFANA_ADMIN_USER` | `admin` | Grafana login |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | |

---

## Checking Logs

```bash
docker compose logs -f backend
docker compose logs -f worker
```

---

## Tearing Down

```bash
# Stop containers but keep databases intact
docker compose down

# WARNING: Stop containers and WIPE all databases and volumes
docker compose down -v
```

---

## Troubleshooting

**"Backend did not become healthy" during `./setup`**

Check the backend logs:
```bash
docker compose logs backend | tail -50
```
Common causes: a stale Postgres volume (run `docker compose down -v` and
retry), or the database port 5432 is already in use.

**Database port 5432 is already in use**

```bash
sudo lsof -i :5432            # find the process
docker compose down            # stop existing DMP containers
```

**Services start but the frontend shows a blank page**

The frontend requires the `frontend` profile.  Run:
```bash
COMPOSE_PROFILES=full ./setup
```

**Compilation error / missing module after pulling new code**

The Docker image may be stale.  Rebuild:
```bash
docker compose build --no-cache backend
docker compose up -d backend
```

**"dvc pull" asks for Google authentication**

DVC is optional.  The `./setup` script automatically falls back to the
20 MB Git LFS sample data, which is enough to explore the API,
metadata, and telemetry endpoints.  Only training and forecasting
require the full DVC dataset.

**Schema migrations fail after `git pull`**

If you pulled new code that includes migration files, run:
```bash
docker compose exec backend alembic upgrade head
```
