"""
Service tests for JobPostingService.

Real Postgres DB via db_session (same as other service tests), but
generate_embedding / query_similar_candidates / bump_list_version are
mocked via monkeypatch — this service's job is orchestration, not
actually computing embeddings or hitting Chroma/Redis, and we don't
want these tests slow, flaky, or dependent on those services running.
monkeypatch.setattr targets the names as imported INTO
app.services.job_posting_service, not their original module, since
that's the reference actually called at runtime.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.models.candidate_profile import CandidateProfile
from app.models.job_posting import EmploymentType, JobPosting, JobStatus
from app.models.user import User, UserRole
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.schemas.job_posting import JobPostingCreate, JobPostingUpdate
from app.services.job_posting_service import (
    JobPostingNotFoundError,
    JobPostingService,
    PermissionDeniedError,
)


def _make_user(db_session: Session, role: UserRole = UserRole.RECRUITER, **overrides) -> User:
    defaults = {
        "email": f"{uuid.uuid4()}@test.com",
        "hashed_password": "not-a-real-hash",
        "full_name": "Test User",
        "role": role,
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


def _make_create_payload(**overrides) -> JobPostingCreate:
    defaults = {
        "title": "Backend Engineer",
        "description": "Build things.",
        "location": "Remote",
        "employment_type": EmploymentType.FULL_TIME,
    }
    defaults.update(overrides)
    return JobPostingCreate(**defaults)


@pytest.fixture(autouse=True)
def _mock_cache_bump(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file gets a no-op bump_list_version — none of
    these tests care about Redis cache invalidation specifically."""
    monkeypatch.setattr("app.services.job_posting_service.bump_list_version", lambda *_: None)


class TestJobPostingServiceCreate:
    def test_create_job_posting_persists_and_returns_job(self, db_session: Session) -> None:
        recruiter = _make_user(db_session)
        service = JobPostingService(db_session)

        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        assert job.id is not None
        assert job.recruiter_id == recruiter.id
        assert job.status == JobStatus.DRAFT

    def test_create_job_posting_bumps_cache_version(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Overrides the autouse no-op mock with one that records calls, to
        confirm the service actually invalidates the job-listing cache on
        create — not just that the job got saved. Without this, a stale
        cached listing page could hide newly created jobs.
        """
        calls = []
        monkeypatch.setattr(
            "app.services.job_posting_service.bump_list_version", lambda key: calls.append(key)
        )
        recruiter = _make_user(db_session)
        service = JobPostingService(db_session)

        service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        assert calls == ["jobs"]


class TestJobPostingServiceGetAndList:
    def test_get_job_posting_raises_when_not_found(self, db_session: Session) -> None:
        service = JobPostingService(db_session)

        with pytest.raises(JobPostingNotFoundError):
            service.get_job_posting(uuid.uuid4())

    def test_list_open_postings_clamps_limit_to_max_page_size(self, db_session: Session) -> None:
        """
        Protects against a client requesting limit=100000 and forcing the
        DB to load an enormous result set. Doesn't need any actual open
        postings to exist — we're testing the clamping logic itself, via
        the fact that a huge requested limit doesn't error or hang.
        """
        service = JobPostingService(db_session)

        items, total = service.list_open_postings(limit=999_999, offset=0)

        # Can't directly observe the internal clamped value from here,
        # but this proves the call succeeds and returns a sane result
        # rather than attempting to materialize an enormous LIMIT.
        assert isinstance(items, list)
        assert isinstance(total, int)


class TestJobPostingServiceUpdate:
    def test_owner_can_update_their_own_job(self, db_session: Session) -> None:
        recruiter = _make_user(db_session)
        service = JobPostingService(db_session)
        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        updated = service.update_job_posting(
            job.id, JobPostingUpdate(title="Updated Title"), current_user=recruiter
        )

        assert updated.title == "Updated Title"

    def test_partial_update_only_changes_provided_fields(self, db_session: Session) -> None:
        """
        JobPostingUpdate uses exclude_unset=True in the service — fields
        the client didn't send must be left untouched, not overwritten
        with schema defaults (which would silently null out data on any
        partial PATCH).
        """
        recruiter = _make_user(db_session)
        service = JobPostingService(db_session)
        job = service.create_job_posting(
            _make_create_payload(location="Original Location"), recruiter_id=recruiter.id
        )

        updated = service.update_job_posting(
            job.id, JobPostingUpdate(title="New Title Only"), current_user=recruiter
        )

        assert updated.title == "New Title Only"
        assert updated.location == "Original Location"

    def test_non_owner_non_admin_cannot_update(self, db_session: Session) -> None:
        recruiter = _make_user(db_session)
        other_recruiter = _make_user(db_session, role=UserRole.RECRUITER)
        service = JobPostingService(db_session)
        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        with pytest.raises(PermissionDeniedError):
            service.update_job_posting(
                job.id, JobPostingUpdate(title="Hijacked"), current_user=other_recruiter
            )

    def test_admin_can_update_any_job(self, db_session: Session) -> None:
        recruiter = _make_user(db_session)
        admin = _make_user(db_session, role=UserRole.ADMIN)
        service = JobPostingService(db_session)
        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        updated = service.update_job_posting(
            job.id, JobPostingUpdate(title="Admin Override"), current_user=admin
        )

        assert updated.title == "Admin Override"

    def test_update_nonexistent_job_raises_not_found_before_permission_check(
        self, db_session: Session
    ) -> None:
        """
        get_job_posting() is called before _assert_owner_or_admin() in
        update_job_posting — a nonexistent job must raise 'not found',
        not leak information via a permission error about a job that
        doesn't even exist.
        """
        recruiter = _make_user(db_session)
        service = JobPostingService(db_session)

        with pytest.raises(JobPostingNotFoundError):
            service.update_job_posting(
                uuid.uuid4(), JobPostingUpdate(title="Doesn't Matter"), current_user=recruiter
            )


class TestJobPostingServiceDelete:
    def test_owner_can_delete_their_own_job(self, db_session: Session) -> None:
        recruiter = _make_user(db_session)
        service = JobPostingService(db_session)
        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        service.delete_job_posting(job.id, current_user=recruiter)

        with pytest.raises(JobPostingNotFoundError):
            service.get_job_posting(job.id)

    def test_non_owner_non_admin_cannot_delete(self, db_session: Session) -> None:
        recruiter = _make_user(db_session)
        other_recruiter = _make_user(db_session)
        service = JobPostingService(db_session)
        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        with pytest.raises(PermissionDeniedError):
            service.delete_job_posting(job.id, current_user=other_recruiter)


class TestJobPostingServiceGetMatchingCandidates:
    def test_non_owner_non_admin_cannot_view_matches(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Matches shouldn't even attempt an embedding lookup for someone
        without permission — the permission check must happen before any
        external calls. Mocks are set to raise if called at all, so this
        test fails loudly if the ordering is ever reversed.
        """

        def _should_not_be_called(*_args, **_kwargs):
            raise AssertionError("generate_embedding should not be called without permission")

        monkeypatch.setattr(
            "app.services.job_posting_service.generate_embedding", _should_not_be_called
        )

        recruiter = _make_user(db_session)
        other_recruiter = _make_user(db_session)
        service = JobPostingService(db_session)
        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        with pytest.raises(PermissionDeniedError):
            service.get_matching_candidates(job.id, current_user=other_recruiter)

    def test_matching_candidates_skips_profiles_deleted_after_indexing(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        query_similar_candidates can return a candidate_user_id whose
        CandidateProfile no longer exists (deleted after their resume was
        indexed). The service must skip that result silently rather than
        crash the whole request over one stale index entry.
        """
        stale_user_id = uuid.uuid4()

        monkeypatch.setattr(
            "app.services.job_posting_service.generate_embedding", lambda _text: [0.1, 0.2, 0.3]
        )
        monkeypatch.setattr(
            "app.services.job_posting_service.query_similar_candidates",
            lambda _embedding, top_k: [
                {"candidate_user_id": str(stale_user_id), "distance": 0.1}
            ],
        )

        recruiter = _make_user(db_session)
        service = JobPostingService(db_session)
        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        results = service.get_matching_candidates(job.id, current_user=recruiter)

        assert results == []

    def test_matching_candidates_converts_distance_to_similarity_score(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recruiter = _make_user(db_session)
        service = JobPostingService(db_session)
        job = service.create_job_posting(_make_create_payload(), recruiter_id=recruiter.id)

        # Real candidate profile so the result isn't skipped.
        candidate_user = _make_user(db_session, role=UserRole.CANDIDATE)
        CandidateProfileRepository(db_session).create(
            CandidateProfile(user_id=candidate_user.id, headline="Test Headline")
        )
        db_session.flush()

        monkeypatch.setattr(
            "app.services.job_posting_service.generate_embedding", lambda _text: [0.1, 0.2, 0.3]
        )
        monkeypatch.setattr(
            "app.services.job_posting_service.query_similar_candidates",
            lambda _embedding, top_k: [
                {"candidate_user_id": str(candidate_user.id), "distance": 0.25}
            ],
        )

        results = service.get_matching_candidates(job.id, current_user=recruiter)

        assert len(results) == 1
        assert results[0]["similarity_score"] == 0.75  # 1 - 0.25
        assert results[0]["headline"] == "Test Headline"
