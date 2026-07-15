"""
Auth service — authentication logic, separate from UserService's registration logic.
"""

from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.repositories.user_repository import UserRepository


class InvalidCredentialsError(Exception):
    """
    Raised for any failed login attempt — wrong email OR wrong password.

    Deliberately a single error type for both cases: returning different
    errors for "email not found" vs "wrong password" lets an attacker
    enumerate which emails are registered. Always show one generic message.
    """


class AuthService:
    """Orchestrates login: credential verification and token issuance."""

    def __init__(self, db: Session) -> None:
        self._repo = UserRepository(db)

    def login(self, email: str, password: str) -> str:
        """
        Verify credentials and return a signed JWT access token.

        Raises:
            InvalidCredentialsError: if the email doesn't exist, the account
                is inactive, or the password doesn't match.
        """
        user = self._repo.get_by_email(email)
        if user is None or not user.is_active:
            raise InvalidCredentialsError("Incorrect email or password")

        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError("Incorrect email or password")

        return create_access_token(user.id)
