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

## 5. Example Workflows

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

## 6. Tearing Down

When you are done working, you can stop the containers.

```bash
# Stop containers but keep the databases (Postgres/Redis) intact
docker compose down

# WARNING: Stop containers and WIPE all local databases and volumes
docker compose down -v

```
