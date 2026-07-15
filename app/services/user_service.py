"""
User service — business logic sits here, not in routes or repositories.
"""

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


class EmailAlreadyRegisteredError(Exception):
    """Raised when attempting to register a user with an email already in use."""


class UserService:
    """Orchestrates user registration and retrieval, enforcing business rules."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = UserRepository(db)

    def register_user(self, payload: UserCreate) -> User:
        """
        Register a new user.

        Raises:
            EmailAlreadyRegisteredError: if the email is already taken.
        """
        existing = self._repo.get_by_email(payload.email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(f"Email already registered: {payload.email}")

        user = User(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            role=payload.role,
        )
        self._repo.create(user)
        self._db.commit()
        self._db.refresh(user)
        return user
