import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.core.config import settings

DATABASE_URL = os.getenv("DATABASE_URL", settings.DATABASE_URL)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Locate alembic.ini relative to this file (backend/src/database.py -> backend/../alembic.ini)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI_PATH = _PROJECT_ROOT / "alembic.ini"


def init_db():
    """Verifies database connectivity only. Migrations are managed by Alembic."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        raise RuntimeError(f"Database connection failed: {e}")


def get_db():
    """Dependency to provide a DB session to FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
