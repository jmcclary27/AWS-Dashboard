# AWS Collaboration Dashboard

A monorepo portfolio project for cost visibility across multiple AWS accounts, starting with a Docker Compose MVP and growing toward Helm-packaged k3d and k3s deployments.

## What is in this scaffold

- `apps/web`: Next.js App Router frontend with Tailwind and Recharts.
- `apps/api`: FastAPI service with SQLAlchemy models, fake seeded cost data, and Phase 1 endpoints.
- `infra`: placeholders for Helm and OpenTofu assets.
- `docs`: architecture and setup notes for the current MVP.

## Current scope

This repository implements the local MVP slice from the attached plan:

- browser-facing dashboard pages for summary, accounts, services, trends, recommendations, anomalies, and settings
- FastAPI endpoints under `/api/v1`
- Postgres-backed fake data for 90 days across multiple AWS accounts and services
- manual sync endpoints that refresh a 14-day rolling demo window
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

## API surface

- `GET /api/v1/accounts`
- `POST /api/v1/accounts`
- `PATCH /api/v1/accounts/{id}`
- `POST /api/v1/accounts/{id}/sync`
- `POST /api/v1/sync/all`
- `GET /api/v1/summary?range=30d|90d|365d`
- `GET /api/v1/services?range=...&account_id=...`
- `GET /api/v1/trends?range=...&group_by=account|service|team`
- `GET /api/v1/forecast`
- `GET /api/v1/recommendations`
- `GET /api/v1/anomalies`

## Notes

- The frontend never reads Postgres directly; all data flows through FastAPI.
- The current sync path is intentionally fake/demo-first so the later AWS billing collector can reuse the same surface area.
- Alembic, GitHub Actions, Helm templates, and OpenTofu rollout assets are staged as the next layer of work after the local MVP.

