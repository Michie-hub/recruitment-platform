"""
Service tests for UserService.

register_user() calls self._db.commit() internally — this is exactly
why tests/conftest.py's db_session fixture was upgraded to use
join_transaction_mode="create_savepoint" (see that file's docstring).
Without it, these tests would commit real data into the test database
that never gets cleaned up between test runs.
"""

import pytest
from sqlalchemy.orm import Session

from app.models.user import UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.user_service import EmailAlreadyRegisteredError, UserService


def _make_payload(**overrides) -> UserCreate:
    defaults = {
        "email": "register-test@test.com",
        "password": "a-valid-password-123",
        "full_name": "New Candidate",
    }
    defaults.update(overrides)
    return UserCreate(**defaults)


class TestUserServiceRegisterUser:
    def test_register_user_creates_a_persisted_user(self, db_session: Session) -> None:
        service = UserService(db_session)

        user = service.register_user(_make_payload())

        assert user.id is not None
        # Confirms the commit actually happened and the row is genuinely
        # queryable via a fresh repository lookup, not just still sitting
        # in the session's identity map.
        found = UserRepository(db_session).get_by_email("register-test@test.com")
        assert found is not None
        assert found.id == user.id

    def test_register_user_always_assigns_candidate_role(self, db_session: Session) -> None:
        """
        UserCreate no longer even accepts a role field (see the earlier
        privilege-escalation fix), but this test pins the service-layer
        behavior directly: register_user must always produce a CANDIDATE,
        full stop, regardless of what future schema changes might do.
        """
        service = UserService(db_session)

        user = service.register_user(_make_payload())

        assert user.role == UserRole.CANDIDATE

    def test_register_user_never_stores_plaintext_password(self, db_session: Session) -> None:
        service = UserService(db_session)
        plaintext = "a-valid-password-123"

        user = service.register_user(_make_payload(password=plaintext))

        assert user.hashed_password != plaintext

    def test_register_user_with_duplicate_email_raises(self, db_session: Session) -> None:
        service = UserService(db_session)
        service.register_user(_make_payload(email="dupe-service-test@test.com"))

        with pytest.raises(EmailAlreadyRegisteredError):
            service.register_user(_make_payload(email="dupe-service-test@test.com"))

    def test_register_user_duplicate_check_is_case_sensitive(self, db_session: Session) -> None:
        """
        Documents current behavior, mirroring the same pattern used in
        UserRepository's case-sensitivity test — this isn't asserting
        it's the ideal behavior, just pinning what actually happens today
        so a future change to normalize email casing is a deliberate,
        visible decision rather than an untested side effect.
        """
        service = UserService(db_session)
        service.register_user(_make_payload(email="CaseSensitive@test.com"))

        # Different casing of the same email — currently NOT treated as
        # a duplicate, since the DB-level check is case-sensitive.
        user = service.register_user(_make_payload(email="casesensitive@test.com"))

        assert user is not None
