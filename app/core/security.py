"""
Password hashing utilities.

Uses argon2id (via argon2-cffi) rather than bcrypt — argon2id is memory-hard
(expensive to attack with GPU/ASIC hardware, not just CPU-bound) and is
OWASP's current recommended default for new systems.

Never import or use these functions outside app/core and app/services —
password handling logic should not leak into repositories or routes.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password for storage. Never store the plaintext itself."""
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored hash. Returns False on any mismatch."""
    try:
        return _hasher.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False
