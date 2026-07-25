"""
Repository tests for CandidateProfileRepository.

Smallest of the three repositories (just get_by_user_id + create), but
the user_id column has a unique=True constraint enforcing "one profile
per user" at the DB level — that constraint is the one thing here worth
testing carefully, since it's easy to declare in the model and forget to
verify it's actually enforced by a real migration.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidate_profile import CandidateProfile
from app.models.user import User
from app.repositories.candidate_profile_repository import CandidateProfileRepository


def _make_candidate_user(db_session: Session, **overrides) -> User:
    defaults = {
        "email": f"{uuid.uuid4()}@test.com",
        "hashed_password": "not-a-real-hash",
        "full_name": "Test Candidate",
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


def _make_profile(user_id: uuid.UUID, **overrides) -> CandidateProfile:
    defaults = {"user_id": user_id, "headline": "Software Engineer"}
    defaults.update(overrides)
    return CandidateProfile(**defaults)


class TestCandidateProfileRepositoryCreate:
    def test_create_assigns_primary_key(self, db_session: Session) -> None:
        user = _make_candidate_user(db_session)
        repo = CandidateProfileRepository(db_session)

        created = repo.create(_make_profile(user.id))

        assert created.id is not None

    def test_create_allows_all_optional_fields_to_be_none(self, db_session: Session) -> None:
        """
        Every profile field except user_id is nullable — a candidate can
        create a bare profile and fill it in incrementally. This confirms
        the repository/model doesn't secretly require something the
        schema layer already treats as optional.
        """
        user = _make_candidate_user(db_session)
        repo = CandidateProfileRepository(db_session)

        created = repo.create(CandidateProfile(user_id=user.id))

        assert created.headline is None
        assert created.bio is None
        assert created.phone is None

    def test_create_rejects_second_profile_for_same_user(self, db_session: Session) -> None:
        """
        user_id is unique=True — this is the core data-integrity rule of
        this table (one profile per user). Proves it's enforced by the DB
        itself, not just assumed by whatever calls the repository.
        """
        user = _make_candidate_user(db_session)
        repo = CandidateProfileRepository(db_session)
        repo.create(_make_profile(user.id))

        with pytest.raises(IntegrityError):
            repo.create(_make_profile(user.id))
            db_session.flush()

    def test_create_rejects_nonexistent_user_id(self, db_session: Session) -> None:
        repo = CandidateProfileRepository(db_session)

        with pytest.raises(IntegrityError):
            repo.create(_make_profile(user_id=uuid.uuid4()))
            db_session.flush()


class TestCandidateProfileRepositoryGetByUserId:
    def test_get_by_user_id_returns_matching_profile(self, db_session: Session) -> None:
        user = _make_candidate_user(db_session)
        repo = CandidateProfileRepository(db_session)
        repo.create(_make_profile(user.id, headline="Findable Headline"))

        found = repo.get_by_user_id(user.id)

        assert found is not None
        assert found.headline == "Findable Headline"

    def test_get_by_user_id_returns_none_when_no_profile_exists(
        self, db_session: Session
    ) -> None:
        user = _make_candidate_user(db_session)
        repo = CandidateProfileRepository(db_session)
        # deliberately no profile created for this user

        found = repo.get_by_user_id(user.id)

        assert found is None

    def test_get_by_user_id_returns_none_for_nonexistent_user_id(
        self, db_session: Session
    ) -> None:
        repo = CandidateProfileRepository(db_session)

        found = repo.get_by_user_id(uuid.uuid4())

        assert found is None
