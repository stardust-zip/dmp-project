import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://dmp_user:dmp_password@localhost:5432/dmp_db"
)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initializes the database tables (creates them if they don't exist)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency to provide a DB session to FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
