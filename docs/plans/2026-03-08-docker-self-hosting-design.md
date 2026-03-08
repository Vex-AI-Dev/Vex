# Docker Self-Hosting — Design Document

**Date:** 2026-03-08
**Status:** Approved

## Problem

Vex has no unified way to self-host the entire stack. Individual Dockerfiles exist for each service, and an infrastructure-only compose lives in `infra/docker/`, but there's no single `docker compose up` that brings up the complete product. For launch, developers need to be able to evaluate Vex locally with zero friction, and self-hosters need a production-ready compose.

## Solution

A root-level `docker-compose.yml` that starts the entire Vex stack — infrastructure, application services, migrations, and Dashboard — with a single command. Docker images published to Docker Hub under `vexhq/` so users can pull pre-built images instead of building locally.

## Architecture

### Containers (12 total)

**Infrastructure (3):**
- PostgreSQL (`timescale/timescaledb-ha:pg16`) — TimescaleDB + pgvector
- Redis (`redis:7-alpine`) — event streaming
- MinIO (`minio/minio`) — S3-compatible object storage

**One-shot (2):**
- `migrations` — runs `alembic upgrade head`, exits
- `createbuckets` — creates MinIO bucket, exits

**Application services (6):**
- `sync-gateway` — main API (verify, ingest)
- `ingestion-api` — ingest-only API
- `async-worker` — background verification + fact extraction
- `storage-worker` — persists events to S3 + PostgreSQL
- `alert-service` — alert evaluation + webhooks
- `dashboard-api` — WebSocket for real-time Dashboard updates

**Frontend (1):**
- `dashboard` — Next.js web UI

### Startup Order

```
postgres (healthcheck: pg_isready)
  └─► migrations (alembic upgrade head, then exits)
       └─► sync-gateway, ingestion-api, async-worker,
           storage-worker, alert-service, dashboard-api

redis (healthcheck: redis-cli ping)
  └─► all application services

minio (healthcheck: curl)
  └─► createbuckets (one-shot)
       └─► storage-worker
```

Application services start only after migrations complete successfully.

### Port Mapping

| Service | Host Port | Purpose |
|---|---|---|
| sync-gateway | 8080 | Main API (SDK clients) |
| ingestion-api | 8081 | Ingest-only API |
| dashboard-api | 8082 | WebSocket real-time |
| dashboard | 3000 | Web UI |
| postgres | 5432 | Database (debug) |
| redis | 6379 | Redis (debug) |
| minio console | 9001 | MinIO UI (debug) |

### Docker Hub Images

Published under `vexhq/`:
- `vexhq/sync-gateway`
- `vexhq/ingestion-api`
- `vexhq/async-worker`
- `vexhq/storage-worker`
- `vexhq/alert-service`
- `vexhq/dashboard-api`
- `vexhq/dashboard`
- `vexhq/migrations`

Tagged with `latest` and git SHA. Infrastructure images pulled from upstream.

## Configuration

### .env.example

```env
# Required: At least one LLM provider
LITELLM_API_URL=
LITELLM_API_KEY=
# OR direct provider keys:
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Required: Embedding provider (for session memory)
TOGETHER_API_KEY=

# Optional: Verification model (default: claude-haiku-4-5-20251001)
VERIFICATION_MODEL=openai/gpt-4o-mini

# Optional: Infrastructure (defaults work out of the box)
POSTGRES_PASSWORD=agentguard_dev
MINIO_ROOT_USER=agentguard
MINIO_ROOT_PASSWORD=agentguard_dev
```

## New Files

| File | Purpose |
|---|---|
| `docker-compose.yml` (root) | Full self-hosting compose |
| `.env.example` (root) | User-facing env template |
| `Dashboard/Dockerfile` | Next.js multi-stage build |
| `services/migrations/Dockerfile` | Alembic migration runner |
| `.github/workflows/docker-publish.yml` | Build & push to Docker Hub |
| `.dockerignore` (root) | Exclude .git, node_modules, venvs |

## User Experience

```bash
git clone https://github.com/vex-hq/Vex.git
cd Vex
cp .env.example .env
# Edit .env — add LLM key(s)
docker compose up
```

Vex runs at `localhost:8080` (API) and `localhost:3000` (Dashboard).
