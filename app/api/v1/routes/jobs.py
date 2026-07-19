"""
Job posting routes.

/api/v1/jobs is public for GET (candidates browse without logging in) but
role-gated for POST, and ownership-gated for PATCH/DELETE (only recruiters/
admins can create postings; only the owning recruiter or an admin can edit
or delete an existing one).
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.dependencies.auth import get_current_user
from app.api.v1.dependencies.rbac import require_role
from app.core.cache import get_json, get_list_version, set_json
from app.core.database import get_db
from app.models.job_posting import JobPosting
from app.models.user import User, UserRole
from app.schemas.job_posting import (
    CandidateMatch,
    JobPostingCreate,
    JobPostingRead,
    JobPostingUpdate,
    PaginatedJobPostings,
)
from app.services.job_posting_service import (
    JobPostingNotFoundError,
    JobPostingService,
    PermissionDeniedError,
)

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

    Cached (cache-aside, 60s TTL): this is the highest-traffic, read-heavy,
    non-personalized endpoint in the platform. The cache key embeds a
    version counter that any job create/update/delete bumps, so a write
    instantly invalidates every previously-cached page of results.
    """
    version = get_list_version("jobs")
    cache_key = f"jobs:list:v{version}:limit={limit}:offset={offset}"

    cached = get_json(cache_key)
    if cached is not None:
        return PaginatedJobPostings.model_validate(cached)

    items, total = JobPostingService(db).list_open_postings(limit=limit, offset=offset)
    result = PaginatedJobPostings(items=items, total=total, limit=limit, offset=offset)

    set_json(cache_key, json.loads(result.model_dump_json()))
    return result


@router.get("/{job_id}", response_model=JobPostingRead)
def get_job_posting(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobPosting:
    """Get a single job posting by ID. Public, regardless of status (a known simplification —
    a stricter version would hide draft/closed postings from non-owners)."""
    try:
        return JobPostingService(db).get_job_posting(job_id)
    except JobPostingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{job_id}", response_model=JobPostingRead)
def update_job_posting(
    job_id: uuid.UUID,
    payload: JobPostingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobPosting:
    """Update a job posting (including publishing a draft by setting status to 'open').
    Only the owning recruiter or an admin may do this."""
    try:
        return JobPostingService(db).update_job_posting(job_id, payload, current_user)
    except JobPostingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/{job_id}", status_code=204)
def delete_job_posting(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a job posting. Only the owning recruiter or an admin may do this."""
    try:
        JobPostingService(db).delete_job_posting(job_id, current_user)
    except JobPostingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{job_id}/matches", response_model=list[CandidateMatch])
def get_job_matches(
    job_id: uuid.UUID,
    top_k: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CandidateMatch]:
    """
    Get candidates ranked by semantic similarity to this job posting.
    Only the owning recruiter or an admin may view matches.
    """
    try:
        return JobPostingService(db).get_matching_candidates(job_id, current_user, top_k=top_k)
    except JobPostingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
