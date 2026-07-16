"""
Candidate profile routes.

/me routes are candidate-only (a recruiter has no reason to have a candidate
profile). The /{user_id} lookup is recruiter/admin-only, since profiles
contain PII (phone, location) that shouldn't be candidate-browsable.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.dependencies.rbac import require_role
from app.core.database import get_db
from app.models.candidate_profile import CandidateProfile
from app.models.user import User, UserRole
from app.schemas.candidate_profile import CandidateProfileRead, CandidateProfileUpsert
from app.services.candidate_profile_service import (
    CandidateProfileNotFoundError,
    CandidateProfileService,
    InvalidResumeFileError,
)

router = APIRouter(prefix="/api/v1/candidates", tags=["candidates"])


@router.post("/me", response_model=CandidateProfileRead)
def upsert_my_profile(
    payload: CandidateProfileUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.CANDIDATE)),
) -> CandidateProfile:
    """Create or update your own candidate profile. Candidate role only."""
    return CandidateProfileService(db).upsert_own_profile(current_user.id, payload)


@router.get("/me", response_model=CandidateProfileRead)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.CANDIDATE)),
) -> CandidateProfile:
    """Get your own candidate profile."""
    try:
        return CandidateProfileService(db).get_profile_by_user_id(current_user.id)
    except CandidateProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{user_id}", response_model=CandidateProfileRead)
def get_candidate_profile(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.RECRUITER, UserRole.ADMIN)),
) -> CandidateProfile:
    """View a specific candidate's profile. Recruiter/admin only — profiles contain PII."""
    try:
        return CandidateProfileService(db).get_profile_by_user_id(user_id)
    except CandidateProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/me/resume", response_model=CandidateProfileRead)
def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.CANDIDATE)),
) -> CandidateProfile:
    """
    Upload/replace your resume (PDF, DOC, or DOCX, max 5MB).
    You must have created a profile via POST /me first.
    """
    try:
        return CandidateProfileService(db).upload_resume(current_user.id, file)
    except CandidateProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidResumeFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/me/resume-url")
def get_my_resume_url(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.CANDIDATE)),
) -> dict[str, str]:
    """Get a temporary (10-minute) signed URL to download your own resume."""
    try:
        url = CandidateProfileService(db).get_resume_download_url(current_user.id)
    except CandidateProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"download_url": url}
