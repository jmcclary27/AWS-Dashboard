# AWS Collaboration Dashboard

A monorepo portfolio project for cost visibility across multiple AWS accounts, starting with a Docker Compose MVP and growing toward Helm-packaged k3d and k3s deployments.

## What is in this scaffold

- `apps/web`: Next.js App Router frontend with Tailwind, Recharts, and connection-scoped views.
- `apps/api`: FastAPI service with SQLAlchemy models, Alembic migrations, demo seeding, and AWS-ready collector routes.
- `infra`: a local k3d Helm chart plus staged OpenTofu assets.
- `docs`: architecture and setup notes for the current connection-scoped MVP.

## Current scope

This repository now implements a connection-scoped MVP slice from the attached plan:

- browser-facing dashboard pages for summary, accounts, services, trends, recommendations, anomalies, and settings
- FastAPI endpoints under `/api/v1` for connection CRUD, sync runs, and connection-scoped analytics
- a built-in demo connection with 90 days of seeded cost data
- AWS-ready org-management and standalone account-role collector seams
- a payable-billing truth layer that uses AWS Data Exports when available and falls back to approximate Cost Explorer net values when it is not
- Docker Compose wiring for `web`, `api`, and `postgres`

## Quick start

1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Open `http://localhost:3000` for the web app.
4. Open `http://localhost:8000/docs` for the FastAPI docs.

## Local Kubernetes (k3d)

The Helm chart runs the same web, API, and PostgreSQL stack in a local k3d cluster. It creates a persistent PostgreSQL volume and a one-shot bootstrap Job that applies migrations and seeds the demo dataset before the API becomes ready.

Install Docker Desktop, `kubectl`, Helm, and k3d first. Then follow [the local Kubernetes guide](docs/kubernetes-local.md) to build/import images, install the chart, optionally provide short-lived AWS credentials, and validate the deployment at `http://dashboard.localhost:8080` (with `http://localhost:8080` as a Windows DNS fallback).

## Real AWS syncs

The app does not store AWS access keys in the database or browser state. AWS-backed syncs use ambient credentials inside the API runtime plus optional role assumption per connection.

1. Authenticate on the host first, for example with `aws sso login --profile your-profile` or temporary environment credentials.
2. Set `AWS_PROFILE` and `AWS_CONFIG_DIR` in `.env`.
3. Start the stack with `docker compose -f docker-compose.yml -f docker-compose.aws.yml up --build`.
4. Open `Settings` and check the `AWS runtime` panel.
5. Configure `billing export bucket`, `prefix`, and `region` on connections where you want exact payable billing truth from AWS Data Exports.
6. Create an `org_management` or `account_role` connection, then use `Validate Access` before running a sync.

## Useful commands

- `docker compose up --build`
- `docker compose -f docker-compose.yml -f docker-compose.aws.yml up --build`
- `docker compose down`
- `python -m pytest apps/api/tests`
- `corepack enable pnpm && pnpm --filter web dev`
- `pnpm --filter web typecheck`

## API surface

- `GET /api/v1/connections`
- `GET /api/v1/aws/runtime`
- `POST /api/v1/connections`
- `GET /api/v1/connections/{id}`
- `PATCH /api/v1/connections/{id}`
- `POST /api/v1/connections/{id}/validate`
- `POST /api/v1/connections/{id}/sync`
- `GET /api/v1/sync-runs?connection_id=...`
- `GET /api/v1/accounts`
- `GET /api/v1/billing/overview?connection_id=...`
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
- Dashboard headline pricing is now payable-first: exact when AWS Data Exports are reachable and fresh, approximate when the app falls back to Cost Explorer net values.
- The safest local AWS path is a read-only `~/.aws` mount or short-lived environment credentials passed only to the `api` container.
- The local Helm chart is ready for k3d; OpenTofu rollout assets, public delivery, monitoring, and scheduled collection remain later infrastructure work.
