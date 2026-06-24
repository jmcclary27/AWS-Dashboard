# Architecture

## Core rule

The browser talks only to FastAPI. The web app never connects to Postgres directly.

## MVP shape

- `apps/web`: dashboards and forms
- `apps/api`: API, connection-scoped collectors, and seeded analytics
- `postgres`: durable storage for canonical accounts, connections, scoped costs, forecasts, recommendations, and anomalies

## Data flow

1. The frontend fetches JSON from `FastAPI /api/v1`, always scoped to one connection.
2. FastAPI reads and writes Postgres through SQLAlchemy 2 models and Alembic-managed schema changes.
3. A built-in demo connection refreshes a rolling 14-day window for local development.
4. Org-management and standalone account-role collectors write through the same scoped tables so datasets stay isolated.
