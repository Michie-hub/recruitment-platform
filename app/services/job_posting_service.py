"""Job posting service — business logic and orchestration."""

import uuid

from sqlalchemy.orm import Session

from app.models.job_posting import JobPosting
from app.repositories.job_posting_repository import JobPostingRepository
from app.schemas.job_posting import JobPostingCreate

MAX_PAGE_SIZE = 100


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
