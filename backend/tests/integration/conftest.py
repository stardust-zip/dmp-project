from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:15") as pg:
        yield pg


def alembic_config(database_url: str):
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="session")
def engine(postgres_container):
    database_url = postgres_container.get_connection_url()
    command.upgrade(alembic_config(database_url), "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()
    command.downgrade(alembic_config(database_url), "base")


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(autocommit=False, autoflush=False, bind=connection)()
    
    yield session
    
    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()
