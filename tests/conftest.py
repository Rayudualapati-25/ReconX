import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session, make_engine
from app.main import create_app

# Tests need a real PostgreSQL: constraints, NUMERIC money and bulk inserts are Postgres-specific.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://reconx:reconx@localhost:5432/reconx_test",
)


def pytest_configure() -> None:
    # The suite drops and recreates the schema, so refuse anything that isn't a test database.
    database = make_url(TEST_DATABASE_URL).database or ""
    if not database.endswith("_test"):
        pytest.exit(f"TEST_DATABASE_URL must name a database ending in _test, got {database!r}")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = make_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test, including work the code commits.

    Commits inside the code under test only release a SAVEPOINT; the outer transaction is
    rolled back at teardown, so tests never see each other's rows.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url=TEST_DATABASE_URL)


@pytest.fixture
def app(settings: Settings, db_session: Session) -> FastAPI:
    """The application, wired to the test's rolled-back session. Tests may add overrides."""
    app = create_app(settings)
    app.dependency_overrides[get_session] = lambda: db_session
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
