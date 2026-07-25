"""
Shared pytest fixtures.

Test DB strategy:
- We point at a SEPARATE Postgres database (recruitment_test), not your dev
  database. Tests must never run against real dev/prod data.
- Tables are created once per test session (fast — avoids CREATE TABLE on
  every single test).
- Each individual test runs inside a transaction that's rolled back at
  teardown. This gives full isolation (no test sees another test's data)
  without the cost of dropping/recreating tables per test.

Why not SQLite for speed: psycopg + your models may use Postgres-specific
behavior (UUID columns, etc.) that SQLite doesn't replicate faithfully.
Testing against a real Postgres, just a disposable one, catches bugs that
an in-memory SQLite DB would silently hide.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app


def _test_database_url() -> str:
    """
    Derive the test DB URL from settings.database_url by swapping the
    database name for 'recruitment_test'. Works regardless of exact URL
    shape (postgresql+psycopg://user:pass@host:port/dbname) as long as
    the database name is the last path segment.
    """
    base_url = settings.database_url
    root, _, _dbname = base_url.rpartition("/")
    return f"{root}/recruitment_test"


TEST_DATABASE_URL = _test_database_url()

test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def _create_test_schema() -> Generator[None, None, None]:
    """
    Runs once for the whole test session. Creates all tables at the start,
    drops them at the end. autouse=True means every test file gets this
    without needing to import it explicitly.

    Requires the 'recruitment_test' database to already exist on your
    Postgres server — see README/setup notes for the one-time
    CREATE DATABASE recruitment_test command.
    """
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """
    Per-test database session, wrapped in a transaction that's rolled back
    at teardown. Use this fixture directly in repository/service tests
    that need a real Session object (not going through the HTTP layer).
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """
    TestClient wired to use the SAME transactional session as db_session,
    via FastAPI's dependency override mechanism. This means an integration
    test that hits a route AND a repository test that hits db_session
    directly are looking at the same isolated transaction — so a test can
    do both (e.g. POST via the client, then assert directly against
    db_session) without them being out of sync.
    """

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
