"""
Job posting routes.

/api/v1/jobs is public for GET (candidates browse without logging in) but
role-gated for POST (only recruiters/admins can create postings).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.dependencies.rbac import require_role
from app.core.database import get_db
from app.models.job_posting import JobPosting
from app.models.user import User, UserRole
from app.schemas.job_posting import JobPostingCreate, JobPostingRead, PaginatedJobPostings
from app.services.job_posting_service import JobPostingService

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.post("", response_model=JobPostingRead, status_code=201)
def create_job_posting(
    payload: JobPostingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.RECRUITER, UserRole.ADMIN)),
) -> JobPosting:
    """Create a job posting. Recruiter/admin only."""
    return JobPostingService(db).create_job_posting(payload, recruiter_id=current_user.id)


@router.get("", response_model=PaginatedJobPostings)
def list_job_postings(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedJobPostings:
    """
    List open job postings. Public — no authentication required, so
    candidates can browse before creating an account.
    """
    items, total = JobPostingService(db).list_open_postings(limit=limit, offset=offset)
    return PaginatedJobPostings(items=items, total=total, limit=limit, offset=offset)
