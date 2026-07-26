# Deployment Guide

This covers deploying the Enterprise AI Recruitment Platform to a production
environment via Docker Compose + Nginx, and the path to running it on AWS.

## 1. Files involved

| File | Purpose |
|---|---|
| `Dockerfile.prod` | Multi-stage production build — no build tools or dev dependencies in the final image, runs as a non-root user |
| `docker-compose.prod.yml` | Production service definitions — no bind mounts, no host-exposed DB/Redis/Chroma/MinIO ports, restart policies |
| `nginx.conf` | Reverse proxy — TLS termination, HTTP→HTTPS redirect, edge-level rate limiting, forwards real client IPs to the app |
| `.env.prod` | **Not committed.** Real secrets for the production environment — see section 2 |

## 2. Required environment variables (`.env.prod`)

Create this file directly on the deployment host. It is never committed to
git (already covered by `.gitignore`) and never baked into the Docker image
(`.dockerignore` explicitly excludes `.env*`).

```
POSTGRES_USER=recruitment_user
POSTGRES_PASSWORD=<generate a real random password — do not reuse the dev value>
POSTGRES_DB=recruitment_db

S3_ACCESS_KEY=<generate a real random key>
S3_SECRET_KEY=<generate a real random secret>
S3_BUCKET_NAME=resumes
S3_PUBLIC_ENDPOINT_URL=https://your-domain.example.com/storage

JWT_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(64))">
```

**On `JWT_SECRET_KEY` specifically:** this must be a long, random, unique
value — never the dev placeholder, never reused across environments. Anyone
who obtains this value can forge valid login tokens for any user, including
admins (see the algorithm-confusion test in `tests/unit/test_security.py`
for what this key is actually protecting against).

## 3. Building and running

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Check everything came up healthy:

```bash
docker compose -f docker-compose.prod.yml ps
```

Every service should show `healthy` or `running` — if `app` is stuck
restarting, check its logs before anything else:

```bash
docker compose -f docker-compose.prod.yml logs app
```

## 4. Database migrations

Migrations run as a one-off command against the `app` image, using
Alembic — never auto-run silently on container startup, since an
unattended failed migration on boot is a worse failure mode than a
deliberate, visible manual step.

```bash
docker compose -f docker-compose.prod.yml exec app alembic upgrade head
```

Run this once after the very first deploy, and again after any deploy that
includes a new migration.

## 5. TLS certificates

`nginx.conf` expects certificate files at `/etc/nginx/certs/fullchain.pem`
and `/etc/nginx/certs/privkey.pem` (mounted read-only from `./certs` on the
host, per `docker-compose.prod.yml`).

**Option A — Let's Encrypt via certbot**, if nginx itself terminates TLS
(the setup described here):
```bash
certbot certonly --standalone -d your-domain.example.com
# copy the resulting fullchain.pem / privkey.pem into ./certs/
```
Certificates expire every 90 days — set up a renewal cron job or systemd
timer calling `certbot renew`, followed by `docker compose -f
docker-compose.prod.yml restart nginx` to pick up the renewed cert.

**Option B — AWS Certificate Manager**, if deploying behind an AWS Application
Load Balancer instead of this nginx container directly (see section 6) — ACM
handles issuance and renewal automatically, and TLS termination happens at
the ALB rather than in nginx at all. In that setup, nginx (or the app
directly) only needs to listen on plain HTTP internally.

## 6. Path to AWS

Two reasonable options, in order of how much this project's current shape
already fits:

### Option A — EC2 + Docker Compose (closest to what's built here)
1. Provision an EC2 instance (Amazon Linux 2023 or Ubuntu), install Docker
   and the Docker Compose plugin.
2. Copy this repo to the instance (or `git clone` if the repo/deploy key is
   accessible), create `.env.prod` directly on the instance, never via git.
3. Run the build/up command from section 3.
4. Point a Route 53 (or your DNS provider's) A record at the instance's
   Elastic IP.
5. Open security group ports 80/443 (and nothing else — DB/Redis/Chroma/
   MinIO have no host-exposed ports in `docker-compose.prod.yml`, so they
   don't need security group rules at all).

Simplest path, closest to local dev, but you own OS patching, Docker
updates, and instance-level monitoring yourself.

### Option B — ECS Fargate (more "cloud-native," more setup)
Each service in `docker-compose.prod.yml` becomes its own ECS task
definition/service. Roughly:
1. Push the built `app` image to ECR (`docker tag` + `docker push`).
2. Postgres, Redis, and MinIO are reasonable candidates to replace with
   managed equivalents instead of running them in containers yourself —
   RDS for Postgres, ElastiCache for Redis, S3 directly instead of MinIO
   (the app already uses an S3-compatible client via boto3, so pointing it
   at real S3 instead of MinIO is a config change, not a code change).
   Chroma has no direct AWS-managed equivalent; it would keep running as
   its own ECS service with an EFS-backed volume for persistence.
2. Define the `app` task with the environment variables from section 2,
   sourced from AWS Secrets Manager rather than plain environment variables
   (ECS supports pulling task-definition secrets directly from Secrets
   Manager or SSM Parameter Store — never hardcode them in the task
   definition JSON).
3. Put an Application Load Balancer in front of the `app` service instead
   of running the `nginx` container — ACM handles TLS at the ALB, and the
   ALB's own listener rules replace `nginx.conf`'s reverse-proxy and
   redirect logic. The app-level rate limiting and security headers stay
   exactly as they are either way, since those live in the application
   code, not in nginx.

More moving parts, more AWS-specific IAM/networking setup, but scales and
self-heals better, and offloads Postgres/Redis operational burden to AWS.

**Recommendation for a portfolio deployment:** Option A is faster to stand
up and demonstrates the same containerized architecture end-to-end; Option B
is worth mentioning you *could* do and why, without necessarily needing to
actually stand it up, unless the goal is specifically to demonstrate ECS/AWS
experience.

## 7. Rollback

Since `docker-compose.prod.yml` builds and tags the app image as
`recruitment-platform-app:prod`, a rollback is: check out the previous
commit/tag, rebuild, redeploy.

```bash
git checkout <previous-known-good-tag>
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

**Migrations complicate rollback** — if the deploy being rolled back
included a migration that isn't backward-compatible (e.g. a dropped
column), the old code may not run correctly against the new schema. This is
a real limitation of the current setup: there's no automated down-migration
step in this runbook. For anything beyond an additive migration (new
nullable column, new table), test the rollback path in a non-production
environment first, or plan the migration itself to be backward-compatible
(expand/contract pattern) rather than relying on `alembic downgrade`.

## 8. Known gaps / follow-up items

- No centralized log aggregation configured (logs currently go to each
  container's stdout, viewable via `docker compose logs`) — for a longer-
  lived deployment, shipping these to CloudWatch Logs (trivial if using ECS,
  requires a log driver config if using EC2 + Compose) would be the next
  step.
- No automated backup schedule for the Postgres volume — `pg_dump` on a
  cron job to S3 is the minimum viable version of this.
- Chroma has no built-in replication/HA story in this setup — a single
  container with a single EFS/EBS-backed volume is a single point of
  failure for semantic search specifically (core app functionality like
  auth, job CRUD, and profiles are unaffected if Chroma is down, since
  matching failures are isolated to that one feature).
