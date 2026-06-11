import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.core.config import settings

DATABASE_URL = os.getenv("DATABASE_URL", settings.DATABASE_URL)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Applies Alembic migrations to bring the database schema to head."""
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def get_db():
    """Dependency to provide a DB session to FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
