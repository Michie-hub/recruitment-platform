"""Schemas for the auth API surface."""

from pydantic import BaseModel


class Token(BaseModel):
    """Response body returned on successful login."""

    access_token: str
    token_type: str = "bearer"
