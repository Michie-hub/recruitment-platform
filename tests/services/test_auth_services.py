"""
Service tests for AuthService.

Unlike repository tests, these exercise a full realistic flow: create a
real user (with a REAL hashed password this time, not the dummy strings
used in repository tests, since login actually verifies against it),
then attempt login and check both the happy path and every failure mode
the service deliberately collapses into one generic error.
"""

import uuid

import jwt
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token, hash_password
from app.models.user import User
from app.services.auth_service import AuthService, InvalidCredentialsError


def _make_active_user(db_session: Session, email: str, password: str, **overrides) -> User:
    defaults = {
        "email": email,
        "hashed_password": hash_password(password),
        "full_name": "Test User",
        "is_active": True,
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


class TestAuthServiceLogin:
    def test_login_with_correct_credentials_returns_valid_token(
        self, db_session: Session
    ) -> None:
        user = _make_active_user(db_session, "login-test@test.com", "correct-password")
        service = AuthService(db_session)

        token = service.login("login-test@test.com", "correct-password")

        # Prove it's not just A string, but a genuinely valid, decodable
        # token for the right user — the full point of login().
        decoded_user_id = decode_access_token(token)
        assert decoded_user_id == user.id

    def test_login_with_wrong_password_raises_invalid_credentials(
        self, db_session: Session
    ) -> None:
        _make_active_user(db_session, "wrongpass-test@test.com", "correct-password")
        service = AuthService(db_session)

        with pytest.raises(InvalidCredentialsError):
            service.login("wrongpass-test@test.com", "wrong-password")

    def test_login_with_nonexistent_email_raises_invalid_credentials(
        self, db_session: Session
    ) -> None:
        service = AuthService(db_session)

        with pytest.raises(InvalidCredentialsError):
            service.login("nobody-registered@test.com", "whatever-password")

    def test_login_with_inactive_account_raises_invalid_credentials(
        self, db_session: Session
    ) -> None:
        """
        is_active=False must block login even with the CORRECT password —
        e.g. a deactivated/banned account. If this failed, a deactivated
        user could still log in and use the platform, defeating the
        purpose of the is_active flag entirely.
        """
        _make_active_user(
            db_session, "inactive-test@test.com", "correct-password", is_active=False
        )
        service = AuthService(db_session)

        with pytest.raises(InvalidCredentialsError):
            service.login("inactive-test@test.com", "correct-password")

    def test_wrong_password_and_nonexistent_email_raise_identical_error_message(
        self, db_session: Session
    ) -> None:
        """
        This is the whole point of InvalidCredentialsError's design (see
        its docstring): wrong-password and email-not-found must be
        INDISTINGUISHABLE to the caller, or an attacker can enumerate
        which emails are registered by noticing a different error message
        or type for each case. This test would fail if someone "improved"
        error messages later by making them more specific per-case.
        """
        _make_active_user(db_session, "enum-test@test.com", "correct-password")
        service = AuthService(db_session)

        wrong_password_message = None
        nonexistent_email_message = None

        try:
            service.login("enum-test@test.com", "wrong-password")
        except InvalidCredentialsError as exc:
            wrong_password_message = str(exc)

        try:
            service.login("nobody-registered-2@test.com", "whatever")
        except InvalidCredentialsError as exc:
            nonexistent_email_message = str(exc)

        assert wrong_password_message == nonexistent_email_message

    def test_login_token_encodes_correct_algorithm(self, db_session: Session) -> None:
        """
        Belt-and-suspenders check tying AuthService to the algorithm
        pinning we already unit-tested in security.py — confirms the
        service doesn't bypass create_access_token and roll its own
        jwt.encode call somewhere with different (weaker) settings.
        """
        _make_active_user(db_session, "algcheck-test@test.com", "correct-password")
        service = AuthService(db_session)

        token = service.login("algcheck-test@test.com", "correct-password")
        header = jwt.get_unverified_header(token)

        assert header["alg"] == settings.jwt_algorithm
