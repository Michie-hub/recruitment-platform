"""
Repository tests for JobPostingRepository.

JobPosting has a required FK to User (recruiter_id), so every test needs
a real persisted User row first — see _make_recruiter() below. This is
a good example of why repository tests sometimes need more setup than
unit tests: we're exercising real FK constraints, not just mocking them
away.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.job_posting import EmploymentType, JobPosting, JobStatus
from app.models.user import User
from app.repositories.job_posting_repository import JobPostingRepository


def _make_recruiter(db_session: Session, **overrides) -> User:
    """
    Persists a real User row to satisfy JobPosting.recruiter_id's FK
    constraint. Uses the session directly rather than UserRepository —
    these are JobPostingRepository tests, so the User creation here is
    setup/fixture data, not the thing under test.
    """
    defaults = {
        "email": f"{uuid.uuid4()}@test.com",
        "hashed_password": "not-a-real-hash",
        "full_name": "Test Recruiter",
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


def _make_job(recruiter_id: uuid.UUID, **overrides) -> JobPosting:
    defaults = {
        "title": "Backend Engineer",
        "description": "Build things.",
        "location": "Remote",
        "employment_type": EmploymentType.FULL_TIME,
        "recruiter_id": recruiter_id,
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


class TestJobPostingRepositoryCreate:
    def test_create_assigns_primary_key(self, db_session: Session) -> None:
        recruiter = _make_recruiter(db_session)
        repo = JobPostingRepository(db_session)

        created = repo.create(_make_job(recruiter.id))

        assert created.id is not None

    def test_create_defaults_status_to_draft(self, db_session: Session) -> None:
        """
        A newly created posting must never be immediately visible/open —
        recruiters publish explicitly. If this default ever silently
        changed to OPEN, unpublished drafts would leak into public
        listings the moment they're saved.
        """
        recruiter = _make_recruiter(db_session)
        repo = JobPostingRepository(db_session)

        created = repo.create(_make_job(recruiter.id))

        assert created.status == JobStatus.DRAFT

    def test_create_rejects_nonexistent_recruiter_id(self, db_session: Session) -> None:
        """
        recruiter_id has a real FK constraint (ForeignKey("users.id")).
        This proves the constraint is actually enforced at the DB level,
        not just declared in the model — a job can't be orphaned to a
        recruiter that doesn't exist.
        """
        from sqlalchemy.exc import IntegrityError

        repo = JobPostingRepository(db_session)
        job = _make_job(recruiter_id=uuid.uuid4())  # no such user

        with pytest.raises(IntegrityError):
            repo.create(job)
            db_session.flush()


class TestJobPostingRepositoryGetById:
    def test_get_by_id_returns_matching_job(self, db_session: Session) -> None:
        recruiter = _make_recruiter(db_session)
        repo = JobPostingRepository(db_session)
        created = repo.create(_make_job(recruiter.id, title="Findable Job"))

        found = repo.get_by_id(created.id)

        assert found is not None
        assert found.title == "Findable Job"

    def test_get_by_id_returns_none_for_nonexistent_id(self, db_session: Session) -> None:
        repo = JobPostingRepository(db_session)

        found = repo.get_by_id(uuid.uuid4())

        assert found is None


class TestJobPostingRepositoryDelete:
    def test_delete_removes_the_job(self, db_session: Session) -> None:
        recruiter = _make_recruiter(db_session)
        repo = JobPostingRepository(db_session)
        job = repo.create(_make_job(recruiter.id))
        job_id = job.id

        repo.delete(job)
        db_session.flush()

        assert repo.get_by_id(job_id) is None


class TestJobPostingRepositoryListOpen:
    def test_list_open_excludes_draft_and_closed(self, db_session: Session) -> None:
        """
        The core contract of list_open: only JobStatus.OPEN postings come
        back, regardless of how many draft/closed postings also exist.
        """
        recruiter = _make_recruiter(db_session)
        repo = JobPostingRepository(db_session)

        repo.create(_make_job(recruiter.id, title="Draft Job", status=JobStatus.DRAFT))
        repo.create(_make_job(recruiter.id, title="Open Job", status=JobStatus.OPEN))
        repo.create(_make_job(recruiter.id, title="Closed Job", status=JobStatus.CLOSED))
        db_session.flush()

        items, total = repo.list_open(limit=10, offset=0)

        assert total == 1
        assert len(items) == 1
        assert items[0].title == "Open Job"

    def test_list_open_total_reflects_full_count_not_page_size(
        self, db_session: Session
    ) -> None:
        """
        Proves 'total' is computed independently of the LIMIT applied to
        'items' — a common pagination bug is accidentally counting only
        the returned page instead of the full matching set.
        """
        recruiter = _make_recruiter(db_session)
        repo = JobPostingRepository(db_session)

        for i in range(5):
            repo.create(_make_job(recruiter.id, title=f"Open Job {i}", status=JobStatus.OPEN))
        db_session.flush()

        items, total = repo.list_open(limit=2, offset=0)

        assert total == 5
        assert len(items) == 2

    def test_list_open_offset_moves_the_window(self, db_session: Session) -> None:
        recruiter = _make_recruiter(db_session)
        repo = JobPostingRepository(db_session)

        for i in range(5):
            repo.create(_make_job(recruiter.id, title=f"Open Job {i}", status=JobStatus.OPEN))
        db_session.flush()

        page_one, _ = repo.list_open(limit=2, offset=0)
        page_two, _ = repo.list_open(limit=2, offset=2)

        page_one_ids = {job.id for job in page_one}
        page_two_ids = {job.id for job in page_two}

        assert page_one_ids.isdisjoint(page_two_ids)

    def test_list_open_orders_newest_first(self, db_session: Session) -> None:
        """
        created_at defaults to datetime.now() at insert time, which on a
        fast test run could theoretically tie at the microsecond level —
        so we set created_at explicitly here rather than relying on real
        wall-clock gaps between three rapid inserts, to keep this test
        deterministic rather than occasionally flaky.
        """
        recruiter = _make_recruiter(db_session)
        repo = JobPostingRepository(db_session)
        base_time = datetime.now(timezone.utc)

        oldest = repo.create(
            _make_job(recruiter.id, title="Oldest", status=JobStatus.OPEN, created_at=base_time)
        )
        newest = repo.create(
            _make_job(
                recruiter.id,
                title="Newest",
                status=JobStatus.OPEN,
                created_at=base_time + timedelta(minutes=10),
            )
        )
        db_session.flush()

        items, _ = repo.list_open(limit=10, offset=0)

        assert items[0].id == newest.id
        assert items[-1].id == oldest.id

    def test_list_open_returns_empty_when_no_open_jobs_exist(self, db_session: Session) -> None:
        repo = JobPostingRepository(db_session)

        items, total = repo.list_open(limit=10, offset=0)

        assert items == []
        assert total == 0
