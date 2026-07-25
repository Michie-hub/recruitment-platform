"""
Integration tests for /api/v1/jobs routes.

Registration always creates a CANDIDATE (by design, see the privilege-
escalation fix), so there's no public HTTP path to create a recruiter
or admin account. For tests needing those roles, we create the User row
directly via db_session and issue a real token with create_access_token
— same approach the service tests used, just now driving real HTTP
requests instead of calling the service directly.

The list endpoint is Redis-cached (see app/core/cache.py) — these tests
run against the REAL Redis via REDIS_HOST=localhost (see .env.test),
not a mock, since cache invalidation-on-write is itself a behavior
worth verifying at this layer.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.cache import bump_list_version
from app.models.job_posting import JobPosting, JobStatus
from app.models.user import User, UserRole
from app.repositories.job_posting_repository import JobPostingRepository


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


def _job_payload(**overrides) -> dict:
    defaults = {
        "title": "Backend Engineer",
        "description": "Build things.",
        "location": "Remote",
        "employment_type": "full_time",
    }
    defaults.update(overrides)
    return defaults


class TestCreateJobPostingEndpoint:
    def test_recruiter_can_create_job_posting(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.RECRUITER)

        response = client.post("/api/v1/jobs", json=_job_payload(), headers=_auth_headers(token))

        assert response.status_code == 201
        assert response.json()["status"] == "draft"

    def test_admin_can_create_job_posting(self, client: TestClient, db_session: Session) -> None:
        _, token = _make_user_with_token(db_session, UserRole.ADMIN)

        response = client.post("/api/v1/jobs", json=_job_payload(), headers=_auth_headers(token))

        assert response.status_code == 201

    def test_candidate_cannot_create_job_posting(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.CANDIDATE)

        response = client.post("/api/v1/jobs", json=_job_payload(), headers=_auth_headers(token))

        assert response.status_code == 403

    def test_unauthenticated_request_cannot_create_job_posting(self, client: TestClient) -> None:
        response = client.post("/api/v1/jobs", json=_job_payload())

        assert response.status_code == 401


class TestListJobPostingsEndpoint:
    def test_list_is_publicly_accessible_without_auth(self, client: TestClient) -> None:
        response = client.get("/api/v1/jobs")

        assert response.status_code == 200

    def test_list_only_returns_open_postings(
        self, client: TestClient, db_session: Session
    ) -> None:
        """
        Inserts directly via the repository rather than through
        JobPostingService.create_job_posting(), so we bump the cache
        version manually here — the direct-DB-write path bypasses the
        cache invalidation the service would normally trigger, and an
        earlier test in this file may have already cached an empty
        result at the same key. Without this, the assertion below fails
        not because the filtering logic is wrong, but because the
        endpoint is correctly serving a stale cache entry that predates
        these inserts.
        """
        recruiter, _ = _make_user_with_token(db_session, UserRole.RECRUITER)
        repo = JobPostingRepository(db_session)
        repo.create(
            JobPosting(
                **_job_payload(title="Open One"), status=JobStatus.OPEN, recruiter_id=recruiter.id
            )
        )
        repo.create(
            JobPosting(
                **_job_payload(title="Draft One"),
                status=JobStatus.DRAFT,
                recruiter_id=recruiter.id,
            )
        )
        db_session.commit()
        bump_list_version("jobs")

        response = client.get("/api/v1/jobs")

        titles = [item["title"] for item in response.json()["items"]]
        assert "Open One" in titles
        assert "Draft One" not in titles

    def test_list_reflects_new_posting_after_cache_invalidation(
        self, client: TestClient, db_session: Session
    ) -> None:
        """
        The list endpoint is cached — this proves a newly published
        posting shows up on the VERY NEXT request, not after a stale
        cache TTL expires. If bump_list_version() were ever removed from
        the create/update path, this test would start failing
        intermittently rather than always, which is exactly the kind of
        bug caching bugs tend to be.
        """
        _, token = _make_user_with_token(db_session, UserRole.RECRUITER)

        client.get("/api/v1/jobs")  # prime the cache before the new job exists

        create_response = client.post(
            "/api/v1/jobs",
            json=_job_payload(title="Freshly Published"),
            headers=_auth_headers(token),
        )
        job_id = create_response.json()["id"]
        client.patch(
            f"/api/v1/jobs/{job_id}", json={"status": "open"}, headers=_auth_headers(token)
        )

        response = client.get("/api/v1/jobs")

        titles = [item["title"] for item in response.json()["items"]]
        assert "Freshly Published" in titles


class TestGetJobPostingEndpoint:
    def test_get_existing_job_returns_200(self, client: TestClient, db_session: Session) -> None:
        _, token = _make_user_with_token(db_session, UserRole.RECRUITER)
        create_response = client.post(
            "/api/v1/jobs", json=_job_payload(), headers=_auth_headers(token)
        )
        job_id = create_response.json()["id"]

        response = client.get(f"/api/v1/jobs/{job_id}")

        assert response.status_code == 200
        assert response.json()["id"] == job_id

    def test_get_nonexistent_job_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/jobs/{uuid.uuid4()}")

        assert response.status_code == 404


class TestUpdateJobPostingEndpoint:
    def test_owner_can_update_their_job(self, client: TestClient, db_session: Session) -> None:
        _, token = _make_user_with_token(db_session, UserRole.RECRUITER)
        create_response = client.post(
            "/api/v1/jobs", json=_job_payload(), headers=_auth_headers(token)
        )
        job_id = create_response.json()["id"]

        response = client.patch(
            f"/api/v1/jobs/{job_id}",
            json={"title": "Updated via HTTP"},
            headers=_auth_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["title"] == "Updated via HTTP"

    def test_non_owner_cannot_update_job(self, client: TestClient, db_session: Session) -> None:
        _, owner_token = _make_user_with_token(db_session, UserRole.RECRUITER)
        _, other_token = _make_user_with_token(db_session, UserRole.RECRUITER)
        create_response = client.post(
            "/api/v1/jobs", json=_job_payload(), headers=_auth_headers(owner_token)
        )
        job_id = create_response.json()["id"]

        response = client.patch(
            f"/api/v1/jobs/{job_id}",
            json={"title": "Hijacked"},
            headers=_auth_headers(other_token),
        )

        assert response.status_code == 403

    def test_update_nonexistent_job_returns_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, token = _make_user_with_token(db_session, UserRole.RECRUITER)

        response = client.patch(
            f"/api/v1/jobs/{uuid.uuid4()}",
            json={"title": "Doesn't Matter"},
            headers=_auth_headers(token),
        )

        assert response.status_code == 404


class TestDeleteJobPostingEndpoint:
    def test_owner_can_delete_their_job(self, client: TestClient, db_session: Session) -> None:
        _, token = _make_user_with_token(db_session, UserRole.RECRUITER)
        create_response = client.post(
            "/api/v1/jobs", json=_job_payload(), headers=_auth_headers(token)
        )
        job_id = create_response.json()["id"]

        response = client.delete(f"/api/v1/jobs/{job_id}", headers=_auth_headers(token))

        assert response.status_code == 204
        assert client.get(f"/api/v1/jobs/{job_id}").status_code == 404

    def test_non_owner_cannot_delete_job(self, client: TestClient, db_session: Session) -> None:
        _, owner_token = _make_user_with_token(db_session, UserRole.RECRUITER)
        _, other_token = _make_user_with_token(db_session, UserRole.RECRUITER)
        create_response = client.post(
            "/api/v1/jobs", json=_job_payload(), headers=_auth_headers(owner_token)
        )
        job_id = create_response.json()["id"]

        response = client.delete(f"/api/v1/jobs/{job_id}", headers=_auth_headers(other_token))

        assert response.status_code == 403


class TestJobMatchesEndpoint:
    def test_non_owner_cannot_view_matches(self, client: TestClient, db_session: Session) -> None:
        _, owner_token = _make_user_with_token(db_session, UserRole.RECRUITER)
        _, other_token = _make_user_with_token(db_session, UserRole.RECRUITER)
        create_response = client.post(
            "/api/v1/jobs", json=_job_payload(), headers=_auth_headers(owner_token)
        )
        job_id = create_response.json()["id"]

        response = client.get(f"/api/v1/jobs/{job_id}/matches", headers=_auth_headers(other_token))

        assert response.status_code == 403

    def test_owner_can_view_matches(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.job_posting_service.generate_embedding", lambda _text: [0.1, 0.2]
        )
        monkeypatch.setattr(
            "app.services.job_posting_service.query_similar_candidates",
            lambda _embedding, top_k: [],
        )
        _, token = _make_user_with_token(db_session, UserRole.RECRUITER)
        create_response = client.post(
            "/api/v1/jobs", json=_job_payload(), headers=_auth_headers(token)
        )
        job_id = create_response.json()["id"]

        response = client.get(f"/api/v1/jobs/{job_id}/matches", headers=_auth_headers(token))

        assert response.status_code == 200
        assert response.json() == []
