"""
Integration tests for /api/v1/candidates routes.

Resume upload/download tests mock the same external boundaries as the
service-layer tests (S3 upload, resume parsing, embeddings, presigned
URLs) — these tests verify routing, RBAC, and request/response wiring,
not MinIO or Chroma correctness.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _make_user_with_token(db_session: Session, role: UserRole, **overrides) -> tuple:
    defaults = {
        "email": f"{uuid.uuid4()}@test.com",
        "hashed_password": hash_password("irrelevant-password"),
        "full_name": "Test User",
        "role": role,
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    token = create_access_token(user.id)
    return user, token


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestUpsertMyProfileEndpoint:
    def test_candidate_can_create_own_profile(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)

        response = client.post(
            "/api/v1/candidates/me",
            json={"headline": "Senior Engineer"},
            headers=_auth_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["headline"] == "Senior Engineer"

    def test_recruiter_cannot_create_candidate_profile(
        self, client: TestClient, db_session: Session
    ) -> None:
        """
        require_role(UserRole.CANDIDATE) — a recruiter account has no
        legitimate reason to have a candidate profile, per the route's
        own module docstring.
        """
        _, token = _make_user_with_token(db_session, UserRole.RECRUITER)

        response = client.post(
            "/api/v1/candidates/me",
            json={"headline": "Trying Anyway"},
            headers=_auth_headers(token),
        )

        assert response.status_code == 403

    def test_upsert_is_idempotent_update_not_duplicate(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)
        first = client.post(
            "/api/v1/candidates/me", json={"headline": "First"}, headers=_auth_headers(token)
        )

        second = client.post(
            "/api/v1/candidates/me", json={"headline": "Second"}, headers=_auth_headers(token)
        )

        assert second.json()["id"] == first.json()["id"]
        assert second.json()["headline"] == "Second"


class TestGetMyProfileEndpoint:
    def test_get_own_profile_after_creating_returns_200(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)
        client.post(
            "/api/v1/candidates/me", json={"headline": "Findable"}, headers=_auth_headers(token)
        )

        response = client.get("/api/v1/candidates/me", headers=_auth_headers(token))

        assert response.status_code == 200
        assert response.json()["headline"] == "Findable"

    def test_get_own_profile_before_creating_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)

        response = client.get("/api/v1/candidates/me", headers=_auth_headers(token))

        assert response.status_code == 404


class TestGetCandidateProfileByIdEndpoint:
    def test_recruiter_can_view_a_candidates_profile(
        self, client: TestClient, db_session: Session
    ) -> None:
        candidate, candidate_token = _make_user_with_token(db_session, UserRole.CANDIDATE)
        client.post(
            "/api/v1/candidates/me",
            json={"headline": "Visible To Recruiters"},
            headers=_auth_headers(candidate_token),
        )
        _, recruiter_token = _make_user_with_token(db_session, UserRole.RECRUITER)

        response = client.get(
            f"/api/v1/candidates/{candidate.id}", headers=_auth_headers(recruiter_token)
        )

        assert response.status_code == 200
        assert response.json()["headline"] == "Visible To Recruiters"

    def test_candidate_cannot_view_another_candidates_profile(
        self, client: TestClient, db_session: Session
    ) -> None:
        """
        PII protection: profiles contain phone/location, per the route
        module's own docstring — a candidate browsing other candidates'
        profiles is exactly what this role restriction exists to prevent.
        """
        target, _ = _make_user_with_token(db_session, UserRole.CANDIDATE)
        _, viewer_token = _make_user_with_token(db_session, UserRole.CANDIDATE)

        response = client.get(
            f"/api/v1/candidates/{target.id}", headers=_auth_headers(viewer_token)
        )

        assert response.status_code == 403


class TestUploadResumeEndpoint:
    def test_upload_resume_without_profile_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)

        response = client.post(
            "/api/v1/candidates/me/resume",
            files={"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            headers=_auth_headers(token),
        )

        assert response.status_code == 404

    def test_upload_resume_rejects_disallowed_file_type(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)
        client.post(
            "/api/v1/candidates/me", json={"headline": "Has Profile"}, headers=_auth_headers(token)
        )

        response = client.post(
            "/api/v1/candidates/me/resume",
            files={"file": ("not-a-resume.png", io.BytesIO(b"fake-png"), "image/png")},
            headers=_auth_headers(token),
        )

        assert response.status_code == 422

    def test_upload_resume_succeeds_with_mocked_storage(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.candidate_profile_service.upload_file", lambda *_, **__: None
        )
        monkeypatch.setattr(
            "app.services.candidate_profile_service.extract_text", lambda *_: "resume text"
        )
        monkeypatch.setattr(
            "app.services.candidate_profile_service.generate_embedding", lambda *_: [0.1, 0.2]
        )
        monkeypatch.setattr(
            "app.services.candidate_profile_service.upsert_candidate_embedding",
            lambda *_: None,
        )
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)
        client.post(
            "/api/v1/candidates/me", json={"headline": "Has Profile"}, headers=_auth_headers(token)
        )

        response = client.post(
            "/api/v1/candidates/me/resume",
            files={"file": ("my_resume.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            headers=_auth_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["resume_filename"] == "my_resume.pdf"


class TestResumeUrlEndpoint:
    def test_resume_url_without_profile_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)

        response = client.get("/api/v1/candidates/me/resume-url", headers=_auth_headers(token))

        assert response.status_code == 404

    def test_resume_url_without_uploaded_resume_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)
        client.post(
            "/api/v1/candidates/me", json={"headline": "No Resume Yet"}, headers=_auth_headers(token)
        )

        response = client.get("/api/v1/candidates/me/resume-url", headers=_auth_headers(token))

        assert response.status_code == 404

    def test_resume_url_returns_presigned_url_after_upload(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.candidate_profile_service.upload_file", lambda *_, **__: None
        )
        monkeypatch.setattr(
            "app.services.candidate_profile_service.extract_text", lambda *_: "resume text"
        )
        monkeypatch.setattr(
            "app.services.candidate_profile_service.generate_embedding", lambda *_: [0.1, 0.2]
        )
        monkeypatch.setattr(
            "app.services.candidate_profile_service.upsert_candidate_embedding",
            lambda *_: None,
        )
        monkeypatch.setattr(
            "app.services.candidate_profile_service.generate_presigned_download_url",
            lambda _key: "https://minio.local/presigned-fake-url",
        )
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)
        client.post(
            "/api/v1/candidates/me", json={"headline": "Has Profile"}, headers=_auth_headers(token)
        )
        client.post(
            "/api/v1/candidates/me/resume",
            files={"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            headers=_auth_headers(token),
        )

        response = client.get("/api/v1/candidates/me/resume-url", headers=_auth_headers(token))

        assert response.status_code == 200
        assert response.json()["download_url"] == "https://minio.local/presigned-fake-url"
