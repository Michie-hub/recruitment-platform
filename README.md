# Enterprise AI Recruitment Platform

An AI-powered recruitment platform built as a portfolio project demonstrating
production-grade backend engineering: layered architecture, RBAC
authentication, semantic candidate–job matching, security hardening, a
127-test suite across four testing layers, and a documented production
deployment path.

## Engineering Highlights

A few things worth pointing out directly, since they don't always show up
just from browsing the code:

- **Found and fixed a privilege-escalation vulnerability**: the original
  registration endpoint exposed a client-settable `role` field, meaning any
  unauthenticated caller could self-register as `admin`. Confirmed the
  exploit end-to-end (`curl` with `role=admin` returned a live admin
  account), fixed it by removing the field from the schema entirely and
  hardcoding role assignment server-side, then wrote both a unit-style
  service test and an HTTP-level integration test that specifically re-proves
  the fix on every test run.
- **A 127-test suite across four layers** — unit (pure logic, no DB),
  repository (real Postgres, real constraints), service (business logic
  and RBAC, external dependencies like S3/ChromaDB mocked), and integration
  (full HTTP round-trips end to end). The integration tier alone caught two
  real bugs that no lower-level test could have seen: a dropped
  `WWW-Authenticate` header (a regression from the centralized error-handling
  work) and a stale-cache test-isolation issue.
- **A real transaction-isolation gotcha, caught before it caused flaky
  tests**: service-layer code that calls `db.commit()` would otherwise
  commit the *real* test database transaction instead of a rollback-able
  one, silently leaking data between tests. Fixed with SQLAlchemy's
  SAVEPOINT-based test isolation (`join_transaction_mode="create_savepoint"`)
  before it ever caused a problem, not after.

## Tech Stack

**Backend:** Python 3.13, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL, Redis
**Auth:** JWT, OAuth2 password flow, RBAC, argon2id password hashing
**AI / Search:** Sentence Transformers (embeddings), ChromaDB (vector store), pypdf (resume text extraction)
**Storage:** S3-compatible object storage (MinIO locally), presigned URLs
**Security:** Redis-backed rate limiting (slowapi), security headers middleware, centralized error handling (no internal detail leakage)
**Testing:** Pytest — unit, repository, service, and integration tiers
**DevOps:** Docker, Docker Compose (dev + production configs), Nginx (reverse proxy, TLS termination), documented AWS deployment path
**Docs:** Swagger / OpenAPI (auto-generated at `/docs`)

**Not currently used, despite what an earlier version of this README said:**
Celery (`app/tasks/` exists but is empty — no background jobs are implemented
yet), LangChain, OpenAI API, spaCy.

## Architecture

Layered architecture with a repository/service pattern:

```
Routes (API layer)  →  Services (business logic)  →  Repositories (data access)  →  Models (ORM)
                              ↓
                         Schemas (Pydantic validation / DTOs)
```

- **Routes** (`app/api/v1/routes/`) — thin controllers only: parse request, call service, shape response. No business logic.
- **Services** (`app/services/`) — business rules, orchestration, transaction boundaries, ownership/RBAC checks that need the actual row.
- **Repositories** (`app/repositories/`) — raw data access only. Never commits transactions — that's the service layer's responsibility, since a service may need to coordinate multiple repository calls in one atomic transaction.
- **Models** (`app/models/`) — SQLAlchemy ORM table definitions.
- **Schemas** (`app/schemas/`) — Pydantic request/response contracts, decoupled from DB shape.

See the codebase docstrings for the reasoning behind specific decisions (why
argon2id over bcrypt, why UUID primary keys, why repositories never call
`commit()`, why registration doesn't accept a `role` field).

## Project Structure

```
recruitment-platform/
├── app/
│   ├── ai/                    # Embeddings, resume text extraction, ChromaDB vector store
│   ├── api/v1/
│   │   ├── routes/            # API endpoints, versioned under /api/v1
│   │   └── dependencies/      # FastAPI Depends() providers (auth, RBAC, DB session)
│   ├── core/                  # Config, logging, security, DB engine/session, caching,
│   │                          # rate limiting, centralized exception handling
│   ├── middleware/             # Security headers middleware
│   ├── models/                  # SQLAlchemy ORM models
│   ├── schemas/                  # Pydantic request/response schemas
│   ├── repositories/              # Data access layer
│   ├── services/                   # Business logic layer
│   ├── tasks/                        # Reserved for future Celery background jobs (unused)
│   └── main.py                        # App factory, router + middleware registration
├── tests/
│   ├── unit/                   # Pure logic, no DB (hashing, JWT)
│   ├── repositories/            # Real Postgres, real constraints
│   ├── services/                  # Business logic, RBAC, external deps mocked
│   ├── integration/                # Full HTTP round-trips via FastAPI's TestClient
│   └── conftest.py                  # Shared fixtures: transactional test DB, HTTP client
├── alembic/                     # Database migrations
├── Dockerfile                    # Development image
├── Dockerfile.prod                # Production image — multi-stage, non-root, no dev deps
├── docker-compose.yml              # Local dev stack
├── docker-compose.prod.yml          # Production stack (see DEPLOYMENT.md)
├── nginx.conf                        # Reverse proxy config for production
├── DEPLOYMENT.md                      # Production deployment runbook
└── requirements.txt
```

## Getting Started (local development)

### Prerequisites
- Docker Desktop (with Docker Compose)

### Setup

1. Clone the repo and copy the environment template:
   ```bash
   cp .env.example .env
   ```
   The placeholder values in `.env.example` work fine for local development.

2. Build and start the stack:
   ```bash
   docker compose up --build
   ```
   This starts five containers: `recruitment_app` (FastAPI), `recruitment_db`
   (Postgres), `recruitment_redis` (Redis), `recruitment_chroma` (ChromaDB
   vector store), `recruitment_minio` (S3-compatible object storage).

   **Note:** Postgres is mapped to host port `5435`, not the default `5432` —
   this repo's dev environment hit a port collision with locally-installed
   native Postgres services during development. If `5435` collides with
   something on your machine too, adjust the `ports:` mapping in
   `docker-compose.yml`.

3. In a second terminal, apply database migrations:
   ```bash
   docker compose exec app alembic upgrade head
   ```

4. Verify it's running:
   ```bash
   curl http://localhost:8000/health
   ```
   Expect: `{"status":"ok","environment":"development"}`

5. Explore the interactive API docs at **http://localhost:8000/docs**

### Running migrations

- Apply all pending migrations: `docker compose exec app alembic upgrade head`
- Create a new migration after changing a model: `docker compose exec app alembic revision --autogenerate -m "description"`
- Roll back one migration: `docker compose exec app alembic downgrade -1`

## Running the tests

Tests run against a real (disposable) Postgres database, not SQLite, since
the models use Postgres-specific behavior. See `tests/conftest.py` for the
full fixture setup.

```bash
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash; use venv/bin/activate on Linux/Mac
pip install -r requirements-dev.txt

# One-time: create the test database
docker compose exec db psql -U <postgres_user> -d postgres -c "CREATE DATABASE recruitment_test;"

# Load local test env overrides (host-reachable ports, not Docker-internal hostnames)
source .env.test

pytest -v
```

Current suite: **127 tests** — 11 unit, 27 repository, 48 service, 41 integration.

## Features

### Foundation
- Docker Compose dev stack (Postgres, Redis, ChromaDB, MinIO, app) with healthcheck-gated startup
- Pydantic Settings-based configuration, structured logging

### Auth & RBAC
- `POST /api/v1/auth/register` — registration with argon2id password hashing (role is always `candidate`, never client-settable)
- `POST /api/v1/auth/login` — OAuth2 password flow, returns a signed JWT access token, rate-limited (5/min)
- `GET /api/v1/auth/me` — protected route, resolves the current user from a bearer token
- Role-based access control (`Admin` / `Recruiter` / `Candidate`) via a `require_role()` dependency

### Job Postings & Candidate Profiles
- **Job postings** (`/api/v1/jobs`): full CRUD, `draft → open → closed` status workflow, offset pagination with a clamped page size, two-layer authorization (role-based creation, resource-ownership-based edit/delete with an admin override), Redis-cached public listing endpoint with write-triggered invalidation
- **Candidate profiles** (`/api/v1/candidates`): upsert-style create/update, recruiter/admin-only lookup by user ID (profiles contain PII)
- **Resume upload**: S3-compatible object storage with content-type/size validation, server-generated collision-proof storage keys, time-limited presigned download URLs

### AI-Powered Matching
- Resume text extraction (PDF) and Sentence Transformer embeddings, indexed in ChromaDB
- `GET /api/v1/jobs/{job_id}/matches` — semantic candidate ranking by similarity to a job posting, owner/admin-only
- Best-effort indexing: a resume upload succeeds even if search indexing fails, logged but non-blocking

### Security Hardening
- Redis-backed rate limiting on `/login` and `/register`
- Security headers middleware (CSP, X-Frame-Options, HSTS on HTTPS, etc.)
- Centralized error handling — every error returns a consistent shape; internal exception details (stack traces, DB errors) are logged server-side but never exposed to the client

### Testing
- 127 tests across unit, repository, service, and integration tiers (see above)

### Deployment
- Multi-stage production Dockerfile (non-root user, no dev dependencies in the runtime image)
- Production Docker Compose config (no bind mounts, no unnecessarily exposed ports)
- Nginx reverse proxy config (TLS termination, edge rate limiting, correct client-IP forwarding)
- Full deployment runbook in [`DEPLOYMENT.md`](./DEPLOYMENT.md) — required environment variables, migration steps, TLS certificate setup, two AWS deployment paths (EC2 + Compose vs. ECS Fargate) with a recommendation, rollback process, and known operational gaps

## API Documentation

Full interactive documentation (request/response schemas, try-it-out) is
auto-generated by FastAPI and available at `/docs` (Swagger UI) or `/redoc`
while the app is running.