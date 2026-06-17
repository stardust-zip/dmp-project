import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import Base
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:15") as pg:
        yield pg


@pytest.fixture(scope="session")
def engine(postgres_container):
    database_url = postgres_container.get_connection_url()
    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


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
