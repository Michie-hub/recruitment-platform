"""
SQLAlchemy engine and session management.

Why a request-scoped session (get_db) instead of one global session:
- SQLAlchemy sessions are NOT thread-safe. Under concurrent requests, a shared
  global session would corrupt state between unrelated requests.
- FastAPI's `Depends(get_db)` creates one session per request and guarantees
  it's closed afterward (even on exception), via the try/finally below.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

# pool_pre_ping=True: checks a connection is alive before handing it out.
# Prevents "server closed the connection unexpectedly" errors after DB
# restarts or long idle periods — cheap insurance in production.

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class every ORM model inherits from."""

    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
