# Architecture

## Core rule

The browser talks only to FastAPI. The web app never connects to Postgres directly.

## MVP shape

- `apps/web`: dashboards and forms
- `apps/api`: API, domain logic, and seeded analytics
- `postgres`: durable storage for accounts, costs, forecasts, recommendations, and anomalies

## Data flow

1. The frontend fetches JSON from `FastAPI /api/v1`.
2. FastAPI reads and writes Postgres through SQLAlchemy 2 models.
3. A demo sync command refreshes the latest 14-day cost window and rebuilds derived findings.
4. Later, the same sync surface will be backed by Cost Explorer collection.

