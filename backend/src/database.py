import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from src.core.config import settings
from src.models import Base

DATABASE_URL = os.getenv("DATABASE_URL", settings.DATABASE_URL)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initializes the database tables (creates them if they don't exist)."""
    Base.metadata.create_all(bind=engine)
    _ensure_user_profile_columns()


def _ensure_user_profile_columns():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    statements: list[str] = []

    if "contact_number" not in existing_columns:
        statements.append("ALTER TABLE users ADD COLUMN contact_number VARCHAR")
    if "status" not in existing_columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN status VARCHAR NOT NULL DEFAULT 'Off_Duty'"
        )
    if "assigned_site_ids" not in existing_columns:
        if engine.dialect.name == "postgresql":
            statements.append(
                "ALTER TABLE users ADD COLUMN assigned_site_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        else:
            statements.append(
                "ALTER TABLE users ADD COLUMN assigned_site_ids JSON NOT NULL DEFAULT '[]'"
            )
    if "is_global_admin" not in existing_columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN is_global_admin BOOLEAN NOT NULL DEFAULT false"
        )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db():
    """Dependency to provide a DB session to FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
