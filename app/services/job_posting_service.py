"""Job posting service — business logic and orchestration."""

import uuid

from sqlalchemy.orm import Session

from app.models.job_posting import JobPosting
from app.models.user import User, UserRole
from app.repositories.job_posting_repository import JobPostingRepository
from app.schemas.job_posting import JobPostingCreate, JobPostingUpdate

MAX_PAGE_SIZE = 100


class JobPostingNotFoundError(Exception):
    """Raised when a job posting ID doesn't exist."""


class PermissionDeniedError(Exception):
    """Raised when a user tries to modify a posting they don't own and isn't an admin."""


class JobPostingService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = JobPostingRepository(db)

    def create_job_posting(self, payload: JobPostingCreate, recruiter_id: uuid.UUID) -> JobPosting:
        job = JobPosting(
            title=payload.title,
            description=payload.description,
            location=payload.location,
            employment_type=payload.employment_type,
            salary_min=payload.salary_min,
            salary_max=payload.salary_max,
            recruiter_id=recruiter_id,
        )
        self._repo.create(job)
        self._db.commit()
        self._db.refresh(job)
        return job

    def list_open_postings(self, limit: int, offset: int) -> tuple[list[JobPosting], int]:
        """Clamps limit to MAX_PAGE_SIZE so a client can't force-load the entire table."""
        safe_limit = min(limit, MAX_PAGE_SIZE)
        return self._repo.list_open(limit=safe_limit, offset=offset)

    def get_job_posting(self, job_id: uuid.UUID) -> JobPosting:
        job = self._repo.get_by_id(job_id)
        if job is None:
            raise JobPostingNotFoundError(f"Job posting not found: {job_id}")
        return job

    def update_job_posting(
        self, job_id: uuid.UUID, payload: JobPostingUpdate, current_user: User
    ) -> JobPosting:
        job = self.get_job_posting(job_id)
        self._assert_owner_or_admin(job, current_user)

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(job, field, value)

        self._db.commit()
        self._db.refresh(job)
        return job

    def delete_job_posting(self, job_id: uuid.UUID, current_user: User) -> None:
        job = self.get_job_posting(job_id)
        self._assert_owner_or_admin(job, current_user)
        self._repo.delete(job)
        self._db.commit()

    @staticmethod
    def _assert_owner_or_admin(job: JobPosting, current_user: User) -> None:
        """
        Resource-level ownership check. Lives here, not in a route dependency,
        because it needs the actual row — unlike role checks, which can be
        answered from the JWT alone before hitting the database.
        """
        is_owner = job.recruiter_id == current_user.id
        is_admin = current_user.role == UserRole.ADMIN
        if not (is_owner or is_admin):
            raise PermissionDeniedError("You do not have permission to modify this job posting")
