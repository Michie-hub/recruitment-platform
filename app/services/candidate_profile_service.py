"""Candidate profile service — business logic and orchestration."""

import uuid

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.storage import generate_presigned_download_url, upload_file
from app.models.candidate_profile import CandidateProfile
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.schemas.candidate_profile import CandidateProfileUpsert

ALLOWED_RESUME_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_RESUME_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


class CandidateProfileNotFoundError(Exception):
    """Raised when a candidate has no profile yet."""


class InvalidResumeFileError(Exception):
    """Raised when an uploaded resume fails type or size validation."""


class CandidateProfileService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = CandidateProfileRepository(db)

    def upsert_own_profile(
        self, user_id: uuid.UUID, payload: CandidateProfileUpsert
    ) -> CandidateProfile:
        """Create the profile if none exists yet, otherwise update the existing one."""
        profile = self._repo.get_by_user_id(user_id)
        update_data = payload.model_dump(exclude_unset=True)

        if profile is None:
            profile = CandidateProfile(user_id=user_id, **update_data)
            self._repo.create(profile)
        else:
            for field, value in update_data.items():
                setattr(profile, field, value)

        self._db.commit()
        self._db.refresh(profile)
        return profile

    def get_profile_by_user_id(self, user_id: uuid.UUID) -> CandidateProfile:
        profile = self._repo.get_by_user_id(user_id)
        if profile is None:
            raise CandidateProfileNotFoundError(f"No candidate profile for user {user_id}")
        return profile

    def upload_resume(self, user_id: uuid.UUID, file: UploadFile) -> CandidateProfile:
        """
        Validate and upload a resume file, attaching it to the candidate's profile.

        Raises:
            CandidateProfileNotFoundError: if the candidate has no profile yet.
            InvalidResumeFileError: if the file type or size is not allowed.
        """
        profile = self.get_profile_by_user_id(user_id)

        if file.content_type not in ALLOWED_RESUME_CONTENT_TYPES:
            raise InvalidResumeFileError(
                f"Unsupported file type: {file.content_type}. Allowed: PDF, DOC, DOCX."
            )

        # file.size is populated by Starlette after reading; validate before upload.
        if file.size is not None and file.size > MAX_RESUME_SIZE_BYTES:
            raise InvalidResumeFileError("Resume file exceeds the 5MB size limit.")

        # Server generates the key — never trust the client's filename as a
        # storage path. UUID prefix prevents collisions and path traversal.
        object_key = f"resumes/{user_id}/{uuid.uuid4()}_{file.filename}"
        upload_file(file.file, object_key, content_type=file.content_type)

        profile.resume_object_key = object_key
        profile.resume_filename = file.filename
        self._db.commit()
        self._db.refresh(profile)
        return profile

    def get_resume_download_url(self, user_id: uuid.UUID) -> str:
        profile = self.get_profile_by_user_id(user_id)
        if profile.resume_object_key is None:
            raise CandidateProfileNotFoundError("No resume uploaded yet")
        return generate_presigned_download_url(profile.resume_object_key)
