"""Schemas for the job postings API surface."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.job_posting import EmploymentType, JobStatus


class JobPostingCreate(BaseModel):
    """Payload for creating a job posting. Status defaults to draft — recruiters publish explicitly."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    location: str = Field(min_length=1, max_length=255)
    employment_type: EmploymentType
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)


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
