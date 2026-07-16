"""Candidate profile service — business logic and orchestration."""

import uuid

from sqlalchemy.orm import Session

from app.models.candidate_profile import CandidateProfile
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.schemas.candidate_profile import CandidateProfileUpsert


class CandidateProfileNotFoundError(Exception):
    """Raised when a candidate has no profile yet."""


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
