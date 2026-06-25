# DMP Smart City AI Platform — Developer Guide

## Quick Start

### Prerequisites

- **Docker & Docker Compose v2.x**
- **Python 3.12+** (for DVC support, optional)
- **Git LFS** (for sample data, installed automatically by Git)

### One-Command Setup

```bash
git clone https://github.com/stardust-zip/dmp-project.git
cd dmp-project
./setup
```

That's it. The setup script is **idempotent** — safe to run repeatedly.
After pulling new code, just run `./setup` again. Your existing data is preserved.

> **Behind the scenes:** `./setup` creates your `.env` (with an interactive profile
> selector), pulls DVC data (or falls back to Git LFS sample data), configures
> Git hooks, builds Docker images, starts services, runs Alembic migrations,
> seeds reference data, and prints URLs for all running services.

### Profiles

Docker Compose profiles let you start only the services you need:

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

This project uses **Alembic** for database migrations (not `create_all()`).

1. **Modify the model** in `backend/src/models.py`.
2. **Generate a migration:**
   ```bash
   cd backend
   DATABASE_URL=postgresql://dmp_user:dmp_password@localhost:5432/dmp_db \
     uv run alembic revision --autogenerate -m "describe_your_change"
   ```
3. **Review** the generated file in `backend/alembic/versions/`.
4. **Apply it:**
   ```bash
   docker compose exec backend alembic upgrade head
   ```
5. **Commit** both the model change and the migration file.

> On existing databases that were created before Alembic was introduced, run
> `docker compose exec backend alembic stamp head` once to mark the current
> state without re-applying migrations.

---

## DVC (Full Dataset)

The full dataset (~4 GB) is managed via DVC with a Google Drive remote.

```bash
# Authenticate (contact the team for credentials)
dvc remote modify --local gdrive gdrive_client_id "YOUR_CLIENT_ID"
dvc remote modify --local gdrive gdrive_client_secret "YOUR_CLIENT_SECRET"

# Pull data
dvc pull
```

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
