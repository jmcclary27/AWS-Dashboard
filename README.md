# AWS Collaboration Dashboard

A monorepo portfolio project for cost visibility across multiple AWS accounts, starting with a Docker Compose MVP and growing toward Helm-packaged k3d and k3s deployments.

## What is in this scaffold

- `apps/web`: Next.js App Router frontend with Tailwind, Recharts, and connection-scoped views.
- `apps/api`: FastAPI service with SQLAlchemy models, Alembic migrations, demo seeding, and AWS-ready collector routes.
- `infra`: placeholders for Helm and OpenTofu assets.
- `docs`: architecture and setup notes for the current connection-scoped MVP.

## Current scope

This repository now implements a connection-scoped MVP slice from the attached plan:

- browser-facing dashboard pages for summary, accounts, services, trends, recommendations, anomalies, and settings
- FastAPI endpoints under `/api/v1` for connection CRUD, sync runs, and connection-scoped analytics
- a built-in demo connection with 90 days of seeded cost data
- AWS-ready org-management and standalone account-role collector seams
- Docker Compose wiring for `web`, `api`, and `postgres`

## Quick start

1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Open `http://localhost:3000` for the web app.
4. Open `http://localhost:8000/docs` for the FastAPI docs.

## Useful commands

- `docker compose up --build`
- `docker compose down`
- `python -m pytest apps/api/tests`
- `corepack enable pnpm && pnpm --filter web dev`
- `pnpm --filter web typecheck`

## API surface

- `GET /api/v1/connections`
- `POST /api/v1/connections`
- `GET /api/v1/connections/{id}`
- `PATCH /api/v1/connections/{id}`
- `POST /api/v1/connections/{id}/sync`
- `GET /api/v1/sync-runs?connection_id=...`
- `GET /api/v1/accounts`
- `POST /api/v1/accounts`
- `PATCH /api/v1/accounts/{id}`
- `POST /api/v1/accounts/{id}/sync`
- `POST /api/v1/sync/all`
- `GET /api/v1/summary?range=30d|90d|365d&connection_id=...`
- `GET /api/v1/services?range=...&account_id=...&connection_id=...`
- `GET /api/v1/trends?range=...&group_by=account|service|team&connection_id=...`
- `GET /api/v1/forecast?connection_id=...`
- `GET /api/v1/recommendations?connection_id=...`
- `GET /api/v1/anomalies?connection_id=...`

## Notes

- The frontend never reads Postgres directly; all data flows through FastAPI.
- The active dashboard scope is one connection at a time so demo, org, and standalone views do not double-count.
- The current local default is still demo-first, but the API and schema now support AWS-backed collector implementations.
- Helm templates and OpenTofu rollout assets remain staged for later infrastructure work.
