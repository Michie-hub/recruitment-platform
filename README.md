# Enterprise AI Recruitment Platform

An AI-powered recruitment platform built as a portfolio project demonstrating
production-grade backend engineering practices: layered architecture, RBAC
authentication, database migrations, and containerized deployment.

## Tech Stack

**Backend:** Python 3.13, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL, Redis, Celery
**Auth:** JWT, OAuth2 password flow, RBAC, argon2id password hashing
**AI (upcoming):** OpenAI API, LangChain, ChromaDB, Sentence Transformers, spaCy
**DevOps:** Docker, Docker Compose, GitHub Actions, AWS, Nginx
**Testing:** Pytest
**Docs:** Swagger / OpenAPI (auto-generated at `/docs`)

## Architecture

Layered architecture with a repository/service pattern:

```
Routes (API layer)  →  Services (business logic)  →  Repositories (data access)  →  Models (ORM)
                              ↓
                         Schemas (Pydantic validation / DTOs)
```

- **Routes** (`app/api/v1/routes/`) — thin controllers only: parse request, call service, shape response. No business logic.
- **Services** (`app/services/`) — business rules, orchestration, transaction boundaries.
- **Repositories** (`app/repositories/`) — raw data access only. Never commits transactions.
- **Models** (`app/models/`) — SQLAlchemy ORM table definitions.
- **Schemas** (`app/schemas/`) — Pydantic request/response contracts, decoupled from DB shape.

See the codebase docstrings for the reasoning behind each architectural decision (e.g. why argon2id over bcrypt, why UUID primary keys, why the repository never calls `commit()`).

## Project Structure

```
recruitment-platform/
├── app/
│   ├── api/v1/
│   │   ├── routes/          # API endpoints, versioned under /api/v1
│   │   └── dependencies/    # FastAPI Depends() providers (auth, RBAC, DB session)
│   ├── core/                # Config, logging, security (hashing + JWT), DB engine/session
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/              # Pydantic request/response schemas
│   ├── repositories/          # Data access layer
│   ├── services/               # Business logic layer
│   ├── ai/                     # (upcoming) LangChain chains, embeddings, resume parsing
│   ├── tasks/                  # (upcoming) Celery background jobs
│   └── main.py                  # App factory, router registration
├── alembic/                     # Database migrations
├── tests/                       # (upcoming) Unit and integration tests
├── docker/Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Getting Started

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
   This starts three containers: `recruitment_app` (FastAPI, port 8000), `recruitment_db` (Postgres, port 5432), `recruitment_redis` (Redis, port 6379).

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

## Current Features

### ✅ Milestone 1 — Foundation
- Docker Compose dev stack (Postgres, Redis, app) with healthcheck-gated startup
- Pydantic Settings-based configuration, structured logging

### ✅ Milestone 2 — Auth & RBAC
- `POST /api/v1/auth/register` — user registration with argon2id password hashing
- `POST /api/v1/auth/login` — OAuth2 password flow, returns a signed JWT access token
- `GET /api/v1/auth/me` — protected route, resolves the current user from a bearer token
- Role-based access control (`Admin` / `Recruiter` / `Candidate`) via a `require_role()` dependency
- Alembic migration for the `users` table

### ✅ Milestone 3 — Job Postings & Candidate Profiles
- **Job postings** (`/api/v1/jobs`): full CRUD, `draft → open → closed` status workflow, offset pagination with a clamped page size, two-layer authorization (role-based creation, resource-ownership-based edit/delete with an admin override)
- **Candidate profiles** (`/api/v1/candidates`): upsert-style create/update, recruiter/admin-only lookup by user ID (profiles contain PII)
- **Resume upload**: S3-compatible object storage (MinIO locally) with content-type/size validation, server-generated collision-proof storage keys, and time-limited presigned download URLs — bucket itself stays private, access is granted per-file and expires

### 🚧 Upcoming
- Milestone 4: AI-powered resume parsing and semantic candidate–job matching (embeddings + ChromaDB), Redis caching, rate limiting, full test coverage pass, production deployment to AWS EC2 behind Nginx

## API Documentation

Full interactive documentation (request/response schemas, try-it-out) is auto-generated by FastAPI and available at `/docs` (Swagger UI) or `/redoc` while the app is running.

