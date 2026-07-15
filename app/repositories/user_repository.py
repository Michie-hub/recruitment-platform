"""
User repository — raw data access only.

Rule: repositories never call db.commit(). Commit is a transaction-boundary
decision that belongs to the service layer, which may need to coordinate
multiple repository calls in one atomic transaction (e.g. create User +
create their default profile row).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Encapsulates all SQL access to the users table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return self._db.execute(stmt).scalar_one_or_none()

    def create(self, user: User) -> User:
        self._db.add(user)
        self._db.flush()  # assigns the PK without committing the transaction
        return user
