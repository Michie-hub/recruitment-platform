"""
Integration tests for /api/v1/auth routes.

Unlike service tests, these go through the FULL stack: real HTTP request
-> FastAPI routing -> dependency injection -> service -> repository ->
real Postgres. This is the tier that catches wiring bugs unit/service
tests structurally can't: wrong route path, wrong status code mapping,
response_model silently dropping a field, a dependency not actually
enforcing what a route's docstring claims.
"""

from fastapi.testclient import TestClient


def _register(client: TestClient, **overrides) -> object:
    payload = {
        "email": "integration-test@test.com",
        "password": "a-valid-password-123",
        "full_name": "Integration Test User",
    }
    payload.update(overrides)
    return client.post("/api/v1/auth/register", json=payload)


def _login(client: TestClient, email: str, password: str) -> object:
    return client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},  # form-encoded, not JSON — see routes/auth.py
    )


class TestRegisterEndpoint:
    def test_register_returns_201_and_user_data(self, client: TestClient) -> None:
        response = _register(client)

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "integration-test@test.com"
        assert body["role"] == "candidate"

    def test_register_never_returns_password_field(self, client: TestClient) -> None:
        """
        UserRead must never leak hashed_password (or anything password-
        related) in the API response — this is exactly the kind of thing
        a response_model schema is supposed to guarantee, and exactly the
        kind of thing that silently breaks if someone swaps UserRead for
        the wrong schema later.
        """
        response = _register(client, email="no-password-leak@test.com")

        body = response.json()
        assert "password" not in body
        assert "hashed_password" not in body

    def test_register_ignores_client_supplied_role(self, client: TestClient) -> None:
        """
        End-to-end proof of the privilege-escalation fix from Milestone 4:
        sending role='admin' in the raw JSON body must not result in an
        admin account. UserCreate no longer has a role field at all, so
        an extra 'role' key here should be silently ignored.
        """
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "escalation-attempt@test.com",
                "password": "a-valid-password-123",
                "full_name": "Attacker",
                "role": "admin",
            },
        )

        assert response.status_code == 201
        assert response.json()["role"] == "candidate"

    def test_register_duplicate_email_returns_409(self, client: TestClient) -> None:
        _register(client, email="duplicate-http-test@test.com")

        second_response = _register(client, email="duplicate-http-test@test.com")

        assert second_response.status_code == 409

    def test_register_with_invalid_email_returns_422_with_error_shape(
        self, client: TestClient
    ) -> None:
        """
        Confirms the centralized error handling from the hardening pass
        is actually wired up for real HTTP requests, not just proven in
        isolation — the response must use the {"error": {...}} shape,
        not FastAPI's raw default.
        """
        response = _register(client, email="not-a-valid-email")

        assert response.status_code == 422
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "validation_error"


class TestLoginEndpoint:
    def test_login_with_correct_credentials_returns_token(self, client: TestClient) -> None:
        _register(client, email="login-flow-test@test.com", password="correct-password-123")

        response = _login(client, "login-flow-test@test.com", "correct-password-123")

        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_login_with_wrong_password_returns_401(self, client: TestClient) -> None:
        _register(client, email="wrong-pw-flow-test@test.com", password="correct-password-123")

        response = _login(client, "wrong-pw-flow-test@test.com", "wrong-password")

        assert response.status_code == 401

    def test_login_response_includes_www_authenticate_header(self, client: TestClient) -> None:
        """
        The 401 response must include WWW-Authenticate: Bearer, per the
        route's explicit headers={"WWW-Authenticate": "Bearer"} — a real
        HTTP-semantics detail a service-layer test can't see at all,
        since it only exists once the exception crosses the route
        boundary into an actual HTTPException.
        """
        response = _login(client, "nobody-registered-flow@test.com", "whatever")

        assert response.headers.get("www-authenticate") == "Bearer"


class TestMeEndpoint:
    def test_me_with_valid_token_returns_current_user(self, client: TestClient) -> None:
        _register(client, email="me-flow-test@test.com", password="correct-password-123")
        login_response = _login(client, "me-flow-test@test.com", "correct-password-123")
        token = login_response.json()["access_token"]

        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["email"] == "me-flow-test@test.com"

    def test_me_without_token_returns_401(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/me")

        assert response.status_code == 401

    def test_me_with_garbage_token_returns_401(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )

        assert response.status_code == 401


class TestAdminOnlyTestEndpoint:
    def test_candidate_cannot_access_admin_only_route(self, client: TestClient) -> None:
        """
        End-to-end proof that require_role() actually blocks the wrong
        role over real HTTP — a newly registered user is always
        CANDIDATE (per the role-escalation fix), so this also indirectly
        re-confirms that fix on every test run.
        """
        _register(client, email="candidate-rbac-test@test.com", password="correct-password-123")
        login_response = _login(client, "candidate-rbac-test@test.com", "correct-password-123")
        token = login_response.json()["access_token"]

        response = client.get(
            "/api/v1/auth/admin-only-test", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 403
