"""Schemas for the candidate profile API surface."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Loose international phone format: optional leading +, 7-15 digits total,
# allowing spaces/dashes/parens for readability. This is deliberately
# permissive — real phone validation (line type, country-specific rules)
# belongs in a library like `phonenumbers`, not a regex. This regex only
# catches obviously-invalid junk like "abc123" or a 2-character string.
PHONE_PATTERN = re.compile(r"^\+?[\d\s\-()]{7,20}$")


class CandidateProfileUpsert(BaseModel):
    """
    Payload for creating or updating your own candidate profile.
    All fields optional — a candidate can fill their profile out incrementally.
    """

    headline: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=5_000)
    skills: str | None = Field(default=None, max_length=1_000, description="Comma-separated list of skills")
    location: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)

    @field_validator("headline", "bio", "skills", "location")
    @classmethod
    def strip_and_blank_to_none(cls, value: str | None) -> str | None:
        """
        Unlike job_posting's title/description, these fields are all
        optional (candidates fill profiles incrementally), so an empty
        result after stripping isn't an error — it just means "not
        provided," and we normalize it to None rather than storing "".
        """
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("phone")
    @classmethod
    def validate_phone_format(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            return None
        if not PHONE_PATTERN.match(stripped):
            raise ValueError(
                "phone must contain 7-20 digits, optionally with +, spaces, dashes, or parentheses"
            )
        return stripped


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
