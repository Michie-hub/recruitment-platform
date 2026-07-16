"""Candidate profile repository — raw data access only."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate_profile import CandidateProfile


class CandidateProfileRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_user_id(self, user_id: uuid.UUID) -> CandidateProfile | None:
        stmt = select(CandidateProfile).where(CandidateProfile.user_id == user_id)
        return self._db.execute(stmt).scalar_one_or_none()

    def create(self, profile: CandidateProfile) -> CandidateProfile:
        self._db.add(profile)
        self._db.flush()
        return profile
