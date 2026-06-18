# DMP Smart City AI Platform - Developer Guide

This guide will walk you through setting up your local environment, syncing our datasets, and spinning up the development servers.

## Prerequisites

Before starting, ensure you have the following installed on your machine:

- **Git**
- **Docker & Docker Compose** (Crucial: Our entire stack is containerized)
- **Python 3.11+**
- _Optional but recommended:_ [uv](https://github.com/astral-sh/uv) for lightning-fast dependency management.

---

## 1. Initial Setup

First, clone the repository and set up your local configuration.

```bash
git clone https://github.com/stardust-zip/dmp-project
cd dmp-project

```

### Git Hooks Configuration

We use a shared pre-push hook to automatically catch syntax errors and verify DVC tracking before code is pushed. Run this command to enable it on your local machine:

```bash
git config core.hooksPath .githooks

# Make the script executable (If you are using Windows, run this with Git Bash)
chmod +x .githooks/pre-push

```

### Environment Variables

```bash
cp .env.example .env

```

---

## 2. Python Environment & Dependencies

We use `pyproject.toml` to manage dependencies. You can set up your local environment using the modern `uv` workflow, or standard `pip`.

### Option A: Using `uv` (Recommended)

If you have `uv` installed:

```bash
# Creates a .venv and installs everything
uv sync

# Activate the environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

```

### Option B: Using Standard `pip`

If you do not use `uv`, you can use standard Python tools to install the project dependencies:

```bash
# Create a virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the project and its development dependencies
pip install -e .
pip install pytest ruff dvc[gdrive]

```

---

## 3. Data Synchronization (DVC)

We use Data Version Control (DVC) linked to a Google Drive bucket.

### Authentication Setup

Run these exact commands in your terminal:

```bash
dvc remote modify --local gdrive gdrive_client_id "ASK_FOR_CLIENT_ID"
dvc remote modify --local gdrive gdrive_client_secret "ASK_FOR_CLIENT_SECRET"

```

### Pulling the Data

Once authenticated, pull the datasets associated with the current Git branch:

```bash
dvc pull

```

_Note: A browser window will open asking you to sign in to Google. Use your authorized work email. If you see a warning about an "unverified app", click **Advanced -> Go to DMP-DVC (unsafe)** to continue._

---

## 4. Running the Full Stack

Our architecture consists of a Postgres DB, Redis broker, MLflow tracking server, FastAPI backend, Celery workers, and a Vite/React frontend.

```bash
# Build and start all services in the background
docker compose up -d --build

```

### Service Map

Once the stack is running, you can access the tools at these URLs:

- **Frontend Dashboard:** http://localhost:3001
- **FastAPI (Swagger UI):** http://localhost:8000/docs
- **JupyterLab (AI Workspace):** http://localhost:8888
- **MLflow (Model Tracking):** http://localhost:5000
- **DbGate (Database GUI):** http://localhost:3002
- **Grafana (Monitoring Dashboard):** http://localhost:3000
- **Prometheus (Metrics Scraper):** http://localhost:9090

### Checking Logs

If something isn't working, you can view the logs for any specific container:

```bash
# View backend API logs
docker compose logs -f backend

# View ML background worker logs
docker compose logs -f worker

```

---

## 5. Database Initialization and Seeding

The backend uses SQLAlchemy's `Base.metadata.create_all()` to initialize the database schema on startup, followed by seeding demo users. This happens when Docker creates or restarts the `backend` container.

For a fresh stack start or after rebuilding the backend image:

```bash
docker compose up -d --build

```

If you need to rerun the backend startup command, recreate only the backend service:

```bash
docker compose up -d --build --force-recreate backend

```

### Making a Database Schema Change

When you add, remove, rename, or change a column/table in `backend/src/models.py`, the schema is automatically synchronized on the next restart via `Base.metadata.create_all()`. For destructive changes (dropping columns/tables, renaming columns, adding `NOT NULL`, changing column types, or backfilling data), write a migration script manually and run it separately before restarting the service.

After standing up the architecture for the first time, your local PostgreSQL database will contain the schema but not the Kaggle telemetry data. Seed it before using telemetry-backed API features or training models.

Run the seeder script through the backend container:

```bash
# Quick Seed: Loads reference data + 1,000 telemetry rows per metric
docker compose exec backend python -m src.seeder

# Custom Seed: Load everything with a specific row cap per metric
docker compose exec backend python -m src.seeder --limit 5000

# Full Seed: Loads the entire historical dataset
docker compose exec backend python -m src.seeder --full

```

### Selective / Phased Seeding

You can seed reference data and telemetry independently, and limit which metrics to load:

```bash
# Phase 1 — Reference data only (locations, devices, metric types)
docker compose exec backend python -m src.seeder --phase reference

# Phase 2 — Telemetry: specific metrics, full dataset
docker compose exec backend python -m src.seeder --phase telemetry \
    --metrics electricity,water,gas --full

# Tune chunk/batch sizes for memory-constrained environments
docker compose exec backend python -m src.seeder --full \
    --chunk-size 5000 --batch-size 5000

```

| Flag | Default | Purpose |
|---|---|---|
| `--phase` | `all` | `reference` / `telemetry` / `weather` / `all` |
| `--metrics` | all 8 | Comma-separated: `electricity,water,gas` |
| `--chunk-size` | 10,000 | CSV rows per pandas chunk (lower = less RAM) |
| `--batch-size` | 10,000 | DB rows per bulk insert |
| `--limit` | 1,000 | Dev-mode row cap per metric |
| `--full` | off | Overrides `--limit` — loads everything |

### Weather data

To seed weather data

```bash
docker compose exec backend python -m src.seeder --phase weather

```

---

## 6. Example Workflows

1. Navigate to **JupyterLab** at `localhost:8888`.
2. The Jupyter container automatically connects to the Postgres database and MLflow. You do not need to mock any database connections.
3. When tracking models, use `mlflow.autolog()` or standard MLflow commands. Your models and metrics will automatically appear in the MLflow UI at `localhost:5000`.
4. **Important:** If you engineer new datasets that the team needs, track them with DVC:

```bash
dvc add data/new_dataset.csv
dvc push
git add data/new_dataset.csv.dvc
git commit -m "data: added new dataset"

```

---

## 7. Tearing Down

When you are done working, you can stop the containers.

```bash
# Stop containers but keep the databases (Postgres/Redis) intact
docker compose down

# WARNING: Stop containers and WIPE all local databases and volumes
docker compose down -v

```
