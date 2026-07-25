"""
Repository tests for UserRepository.

These hit a REAL database (the recruitment_test DB via the db_session
fixture in tests/conftest.py), unlike test_security.py which was pure
logic. This tier catches things unit tests can't: actual SQL constraint
behavior (unique email), whether flush() really does assign a PK without
committing, whether defaults declared on the model actually apply when a
row is persisted.

Repository methods never call commit() (see the module docstring on
UserRepository) — db_session.flush() is what makes data visible/queryable
within the same transaction, and the transaction is rolled back by the
fixture after each test, so nothing here touches real dev data.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository


def _make_user(**overrides) -> User:
    """
    Builds a valid User with sensible defaults, overridable per test.
    hashed_password is a dummy string here on purpose — the repository
    layer doesn't know or care what a "real" hash looks like, that's
    security.py's concern, not the repository's. Keeping it a plain
    string keeps these tests fast and focused on data access, not hashing.
    """
    defaults = {
        "email": f"{uuid.uuid4()}@test.com",  # unique per call, avoids collisions across tests
        "hashed_password": "not-a-real-hash",
        "full_name": "Test User",
    }
    defaults.update(overrides)
    return User(**defaults)


class TestUserRepositoryCreate:
    def test_create_assigns_primary_key(self, db_session: Session) -> None:
        repo = UserRepository(db_session)
        user = _make_user()

        created = repo.create(user)

        assert created.id is not None
        assert isinstance(created.id, uuid.UUID)

    def test_create_applies_model_defaults(self, db_session: Session) -> None:
        """
        Confirms role/is_active defaults declared on the User model
        actually take effect once the row is flushed — these are
        server/ORM-level defaults, not something the repository sets
        itself, so this is really testing the model+repository together.
        """
        repo = UserRepository(db_session)
        user = _make_user()  # no role/is_active passed explicitly

        created = repo.create(user)

        assert created.role == UserRole.CANDIDATE
        assert created.is_active is True
        assert created.created_at is not None

    def test_create_does_not_commit(self, db_session: Session) -> None:
        """
        Repositories only flush, never commit — that's a deliberate
        architectural rule (see UserRepository's module docstring) so the
        service layer controls transaction boundaries. We can't directly
        observe "was COMMIT called" from here, but we can confirm the row
        is queryable within the SAME session after create() without an
        explicit db_session.commit() — proving flush() alone was enough
        to make it visible inside this transaction.
        """
        repo = UserRepository(db_session)
        user = _make_user(email="flush-only@test.com")
        repo.create(user)

        found = repo.get_by_email("flush-only@test.com")

        assert found is not None
        assert found.email == "flush-only@test.com"

    def test_create_duplicate_email_raises_integrity_error(self, db_session: Session) -> None:
        """
        email has a unique constraint at the DB level. This proves that
        constraint is real and enforced — not just declared in the model
        but never actually applied via migrations. If someone dropped the
        unique index in a migration by mistake, this test would catch it.
        """
        repo = UserRepository(db_session)
        repo.create(_make_user(email="dupe@test.com"))

        with pytest.raises(IntegrityError):
            repo.create(_make_user(email="dupe@test.com"))
            db_session.flush()


class TestUserRepositoryGetById:
    def test_get_by_id_returns_matching_user(self, db_session: Session) -> None:
        repo = UserRepository(db_session)
        created = repo.create(_make_user(email="findme@test.com"))

        found = repo.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.email == "findme@test.com"

    def test_get_by_id_returns_none_for_nonexistent_id(self, db_session: Session) -> None:
        repo = UserRepository(db_session)

        found = repo.get_by_id(uuid.uuid4())

        assert found is None


class TestUserRepositoryGetByEmail:
    def test_get_by_email_returns_matching_user(self, db_session: Session) -> None:
        repo = UserRepository(db_session)
        repo.create(_make_user(email="lookup@test.com"))

        found = repo.get_by_email("lookup@test.com")

        assert found is not None
        assert found.email == "lookup@test.com"

    def test_get_by_email_returns_none_for_nonexistent_email(self, db_session: Session) -> None:
        repo = UserRepository(db_session)

        found = repo.get_by_email("nobody-registered@test.com")

        assert found is None

    def test_get_by_email_is_case_sensitive(self, db_session: Session) -> None:
        """
        Documents current behavior rather than asserting it's necessarily
        'correct' — email lookups being case-sensitive at the DB level is
        a common source of real bugs (user registers as 'Foo@x.com', later
        logs in as 'foo@x.com', lookup fails). This test doesn't fix that,
        it makes the current behavior explicit and visible, so if this
        ever gets fixed with a citext column or lower()-normalization,
        this test will fail and force a conscious update rather than the
        behavior silently changing.
        """
        repo = UserRepository(db_session)
        repo.create(_make_user(email="CaseTest@test.com"))

        found = repo.get_by_email("casetest@test.com")

        assert found is None
