"""
Pydantic schemas — the API's request/response contract.

Why separate schemas from the ORM model instead of returning User directly:
- Never leak `hashed_password` in an API response (UserRead deliberately omits it)
- Input validation (e.g. EmailStr format) happens here, decoupled from storage shape
- The API contract can evolve independently of the DB schema
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    """Payload for creating a new user. Plaintext password only ever lives here, briefly."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.CANDIDATE


class UserRead(BaseModel):
    """Safe user representation returned by the API. No password field, ever."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
