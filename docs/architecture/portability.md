# Project Portability

**Status:** Implemented
**Version:** 1.0.0
**Last Updated:** 2026-06-25
**Implementation Plan:** [implementation-plan.md](./implementation-plan.md)

---

## Overview

This document describes the portability improvements made to the DMP Smart City
AI Platform, enabling a **single-command bootstrap** and **safe incremental
schema migrations**. The work is detailed in the
[implementation plan](./implementation-plan.md).

## What Changed

| Dimension | Before | After |
|-----------|--------|-------|
| Developer setup | ~10 manual README steps | `./setup` (1 command, idempotent) |
| Schema management | `create_all()` + ad-hoc ALTER TABLE | Alembic auto-migrations, versioned in Git |
| Service startup | All 10 services always start | Compose profiles (`--profile backend`) |
| Data strategy | DVC-only (GDrive auth required) | Three-tier: DVC → sample-data → zero-data |
| Env configuration | Single `.env.example`, no profiles | Profile-driven with `COMPOSE_PROFILES` |
| Build reproducibility | `dbgate:latest`, `uv pip install --system` | Pinned tags, `uv sync --frozen` |

## Key Files

| File | Purpose |
|------|---------|
| `./setup` | Idempotent entrypoint script |
| `docker-compose.yml` | Profiles + Alembic startup command |
| `backend/alembic/` | Migration framework (18 tables) |
| `backend/src/api/v1/endpoints/system.py` | System status endpoint |
| `sample-data/` | Git LFS-tracked sample data (~20 MB) |
| `backend/Dockerfile` | Optimized layer caching with `uv sync` |
