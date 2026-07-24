"""Schemas for the job postings API surface."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.job_posting import EmploymentType, JobStatus


class JobPostingCreate(BaseModel):
    """Payload for creating a job posting. Status defaults to draft — recruiters publish explicitly."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=20_000)
    location: str = Field(min_length=1, max_length=255)
    employment_type: EmploymentType
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)

    @field_validator("title", "description", "location")
    @classmethod
    def strip_and_require_nonblank(cls, value: str) -> str:
        """
        Reject whitespace-only strings. min_length=1 alone lets "   " through
        since Pydantic counts characters, not meaningful content — a title of
        "   " satisfies min_length=1 but is garbage data.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank or whitespace-only")
        return stripped

    @model_validator(mode="after")
    def validate_salary_range(self) -> "JobPostingCreate":
        """
        Cross-field check: if both salary bounds are given, min must not
        exceed max. Neither field alone can catch this — each is validated
        independently by Field(ge=0), so this only makes sense once both
        values are known, hence a model-level validator instead of a
        field-level one.
        """
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        return self


class JobPostingUpdate(BaseModel):
    """
    Payload for updating a job posting. All fields optional — PATCH semantics,
    only the fields the client sends are changed.
    """

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=20_000)
    location: str | None = Field(default=None, min_length=1, max_length=255)
    employment_type: EmploymentType | None = None
    status: JobStatus | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)

    @field_validator("title", "description", "location")
    @classmethod
    def strip_and_require_nonblank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank or whitespace-only")
        return stripped

    @model_validator(mode="after")
    def validate_salary_range(self) -> "JobPostingUpdate":
        """
        Same cross-field rule as JobPostingCreate. Note this only catches the
        case where BOTH values arrive in the same PATCH request — it can't
        catch "this update's salary_min now exceeds the salary_max already
        stored in the DB from a previous request." That case has to be
        checked in the service layer, where the existing row is available.
        """
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        return self


class JobPostingRead(BaseModel):
    """Job posting as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    location: str
    employment_type: EmploymentType
    status: JobStatus
    salary_min: int | None
    salary_max: int | None
    recruiter_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CandidateMatch(BaseModel):
    """A candidate ranked by semantic similarity to a job posting."""

    candidate_user_id: uuid.UUID
    similarity_score: float = Field(description="0-1, higher means more semantically similar")
    headline: str | None
    skills: str | None
    location: str | None


class PaginatedJobPostings(BaseModel):
    """
    Envelope for paginated list responses.

    total lets the client render 'page 3 of 12' style UI without a second
    request; items is just the current page's slice.
    """

    items: list[JobPostingRead]
    total: int
    limit: int
    offset: int
