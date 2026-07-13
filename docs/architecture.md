# Architecture

## Core rule

The browser uses Next.js for the Cognito session flow and FastAPI for application data. Neither the browser nor the web app connects to Postgres directly. FastAPI is the sole authorization boundary for workspaces and connections. Production keeps the API under the same public host at `/api` so the secure session cookie reaches both services.

## MVP shape

- `apps/web`: Cognito Managed Login handlers, dashboards, workspace selector, and role-aware forms
- `apps/api`: JWT verification, workspace authorization, API, connection-scoped collectors, audit events, and seeded analytics
- `postgres`: durable storage for users, workspaces, memberships, invites, audit events, canonical accounts, connections, scoped costs, forecasts, recommendations, and anomalies

## Data flow

1. Next.js completes the authorization-code + PKCE exchange with Cognito and stores access and refresh tokens in HTTP-only cookies.
2. The frontend fetches JSON from `FastAPI /api/v1`, always scoped to an authorized workspace and connection.
3. FastAPI verifies the Cognito access token, upserts the internal user, resolves the workspace role, and reads or writes Postgres through SQLAlchemy 2 models and Alembic-managed schema changes.
4. A system-owned Demo Workspace exposes a read-only built-in demo connection with seeded synthetic data to signed-in users; normal users cannot request demo syncs.
5. Org-management and standalone account-role collectors write through the same scoped tables so datasets stay isolated. `external_id` remains write-only and is excluded from APIs and audit metadata.

## Local Kubernetes shape

The k3d Helm release keeps the browser-to-FastAPI boundary intact. Traefik sends `/api` to the API service and all other requests to the web service. PostgreSQL is a single persisted StatefulSet. A revision-named bootstrap Job waits for PostgreSQL, applies Alembic migrations, and seeds the demo data; API readiness stays false until the database is at the migration head. Cognito wiring is opt-in in the chart because the default local ingress is not a public TLS endpoint.
