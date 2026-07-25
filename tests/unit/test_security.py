"""
Unit tests for app/core/security.py.

No database, no HTTP — these test pure functions in isolation. This is
the cheapest, fastest tier of testing: if these fail, you know the bug
is in hashing/token logic itself, not in how something else calls it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_password_returns_different_string_than_input(self) -> None:
        plain = "correct-horse-battery-staple"
        hashed = hash_password(plain)
        assert hashed != plain

    def test_hash_password_is_nondeterministic(self) -> None:
        """
        argon2id includes a random salt per hash, so hashing the same
        password twice must produce two DIFFERENT hashes. If this test
        ever fails, it means salting is broken — a serious regression,
        since identical passwords would then produce identical hashes,
        letting an attacker spot reused passwords across accounts.
        """
        plain = "correct-horse-battery-staple"
        hash_one = hash_password(plain)
        hash_two = hash_password(plain)
        assert hash_one != hash_two

    def test_verify_password_succeeds_with_correct_password(self) -> None:
        plain = "correct-horse-battery-staple"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_password_fails_with_incorrect_password(self) -> None:
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_verify_password_fails_with_empty_string(self) -> None:
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("", hashed) is False

    def test_verify_password_does_not_raise_on_malformed_hash(self) -> None:
        """
        If the stored hash is garbage (corrupted DB row, wrong column,
        etc.), verify_password must return False, not raise — a route
        calling this during login shouldn't 500 because of bad stored
        data, it should just fail auth like any other wrong password.
        """
        assert verify_password("anything", "not-a-real-hash") is False


class TestAccessTokens:
    def test_create_and_decode_roundtrip_returns_same_user_id(self) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        decoded_user_id = decode_access_token(token)
        assert decoded_user_id == user_id

    def test_decode_rejects_tampered_token(self) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        tampered = token[:-4] + "abcd"  # corrupt the signature portion
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(tampered)

    def test_decode_rejects_token_signed_with_wrong_secret(self) -> None:
        """
        Simulates a forged token — someone guessing/using a different
        secret to sign a payload. Must be rejected, proving the app
        actually verifies the signature rather than trusting the payload.
        """
        forged_payload = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        forged_token = jwt.encode(
            forged_payload, "a-completely-different-secret", algorithm=settings.jwt_algorithm
        )
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(forged_token)

    def test_decode_rejects_expired_token(self) -> None:
        """
        Builds a token that expired in the past, bypassing
        create_access_token's normal expiry calculation so the test
        doesn't have to sleep in real time to prove expiry is enforced.
        """
        expired_payload = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        expired_token = jwt.encode(
            expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(expired_token)

    def test_decode_rejects_token_with_no_algorithm_match(self) -> None:
        """
        Guards against algorithm-confusion attacks: a token must be
        rejected if it wasn't signed with the algorithm the app expects,
        even if the secret happens to be reused. decode_access_token
        pins `algorithms=[settings.jwt_algorithm]` explicitly for this
        reason — this test proves that pin is actually effective.
        """
        payload = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        # HS512 instead of whatever settings.jwt_algorithm actually is
        # (almost certainly HS256) — decode must reject the mismatch.
        other_algorithm = "HS512" if settings.jwt_algorithm != "HS512" else "HS384"
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=other_algorithm)
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(token)
