"""
Password hashing and JWT utilities.

Uses argon2id (via argon2-cffi) rather than bcrypt — argon2id is memory-hard
(expensive to attack with GPU/ASIC hardware, not just CPU-bound) and is
OWASP's current recommended default for new systems.

Never import or use these functions outside app/core and app/services —
password/token handling logic should not leak into repositories or routes.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password for storage. Never store the plaintext itself."""
    return _hasher.hash(plain_password)


   
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored hash. Returns False on any mismatch or malformed hash."""
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False

def create_access_token(user_id: uuid.UUID) -> str:
    """
    Issue a signed, short-lived JWT access token for the given user.

    The payload deliberately contains only the user ID ('sub') and expiry —
    never put passwords or other sensitive data in a JWT payload, since it's
    base64-encoded, not encrypted, and readable by anyone holding the token.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """
    Verify and decode a JWT access token, returning the user ID it was issued for.

    Explicitly restricts `algorithms` to prevent algorithm-confusion attacks,
    where a token signed with a different/weaker algorithm could otherwise
    be accepted as valid.

    Raises:
        jwt.InvalidTokenError: if the token is expired, malformed, or has a bad signature.
    """
    payload = jwt.decode(
        token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    return uuid.UUID(payload["sub"])

