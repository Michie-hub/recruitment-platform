"""Schemas for the candidate profile API surface."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CandidateProfileUpsert(BaseModel):
    """
    Payload for creating or updating your own candidate profile.
    All fields optional — a candidate can fill their profile out incrementally.
    """

    headline: str | None = Field(default=None, max_length=255)
    bio: str | None = None
    skills: str | None = Field(default=None, description="Comma-separated list of skills")
    location: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)


class CandidateProfileRead(BaseModel):
    """Candidate profile as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    headline: str | None
    bio: str | None
    skills: str | None
    location: str | None
    phone: str | None
    resume_filename: str | None
    created_at: datetime
    updated_at: datetime
