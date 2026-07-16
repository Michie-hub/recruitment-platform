"""Job posting repository — raw data access only."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.job_posting import JobPosting, JobStatus


class JobPostingRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, job: JobPosting) -> JobPosting:
        self._db.add(job)
        self._db.flush()
        return job

    def get_by_id(self, job_id: uuid.UUID) -> JobPosting | None:
        return self._db.get(JobPosting, job_id)

    def delete(self, job: JobPosting) -> None:
        self._db.delete(job)

    def list_open(self, limit: int, offset: int) -> tuple[list[JobPosting], int]:
        """
        Returns (page of open postings, total count of open postings).

        Two queries (one for the page, one for the count) is the standard
        pattern for offset pagination — computing 'total' from the page
        result alone isn't possible once you've already limited it.
        """
        base_stmt = select(JobPosting).where(JobPosting.status == JobStatus.OPEN)

        items = list(
            self._db.execute(
                base_stmt.order_by(JobPosting.created_at.desc()).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )

        total = self._db.execute(
            select(func.count()).select_from(base_stmt.subquery())
        ).scalar_one()

        return items, total
