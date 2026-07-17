"""Candidate profile service — business logic and orchestration."""

import io
import uuid

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.ai.embeddings import generate_embedding
from app.ai.resume_parser import UnsupportedResumeFormatError, extract_text
from app.ai.vector_store import upsert_candidate_embedding
from app.core.logging import get_logger
from app.core.storage import generate_presigned_download_url, upload_file
from app.models.candidate_profile import CandidateProfile
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.schemas.candidate_profile import CandidateProfileUpsert

logger = get_logger(__name__)

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

        Reads the file into memory once, upfront, and reuses those bytes for
        both the S3 upload and search indexing — safer than trying to re-read
        or seek the original stream afterward, since boto3's upload closes it.

        Raises:
            CandidateProfileNotFoundError: if the candidate has no profile yet.
            InvalidResumeFileError: if the file type or size is not allowed.
        """
        profile = self.get_profile_by_user_id(user_id)

        if file.content_type not in ALLOWED_RESUME_CONTENT_TYPES:
            raise InvalidResumeFileError(
                f"Unsupported file type: {file.content_type}. Allowed: PDF, DOC, DOCX."
            )

        file_bytes = file.file.read()
        if len(file_bytes) > MAX_RESUME_SIZE_BYTES:
            raise InvalidResumeFileError("Resume file exceeds the 5MB size limit.")

        # Server generates the key — never trust the client's filename as a
        # storage path. UUID prefix prevents collisions and path traversal.
        object_key = f"resumes/{user_id}/{uuid.uuid4()}_{file.filename}"
        upload_file(io.BytesIO(file_bytes), object_key, content_type=file.content_type)

        profile.resume_object_key = object_key
        profile.resume_filename = file.filename
        self._db.commit()
        self._db.refresh(profile)

        self._index_resume_for_search(user_id, file_bytes, file.content_type)

        return profile

    def _index_resume_for_search(self, user_id: uuid.UUID, file_bytes: bytes, content_type: str) -> None:
        """
        Extract text and store an embedding for semantic search.

        Best-effort and non-blocking to the caller's success path: a failure
        here is logged, not raised — a broken search index shouldn't prevent
        the core action (uploading a resume) from succeeding. Known scope
        limitation: only PDF text extraction is implemented (see resume_parser.py).
        """
        try:
            text = extract_text(file_bytes, content_type)
            if not text:
                logger.warning("Resume for user %s extracted to empty text; skipping indexing", user_id)
                return
            embedding = generate_embedding(text)
            upsert_candidate_embedding(str(user_id), embedding, text)
        except UnsupportedResumeFormatError:
            logger.info(
                "Skipping search indexing for user %s: unsupported format %s", user_id, content_type
            )
        except Exception:
            logger.exception("Failed to index resume for search, user %s", user_id)

    def get_resume_download_url(self, user_id: uuid.UUID) -> str:
        profile = self.get_profile_by_user_id(user_id)
        if profile.resume_object_key is None:
            raise CandidateProfileNotFoundError("No resume uploaded yet")
        return generate_presigned_download_url(profile.resume_object_key)