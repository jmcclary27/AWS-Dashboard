# Local Setup

## Compose path

1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Visit `http://localhost:3000`.

## Host path

Frontend host workflows expect `pnpm`, while the API uses Python tooling.

- `corepack enable pnpm`
- `pnpm --filter web install`
- `pnpm --filter web dev`
- `python -m venv .venv`
- `.venv\\Scripts\\activate`
- `pip install -e apps/api[dev]`
- `uvicorn app.main:app --app-dir apps/api --reload`

## Demo behavior

The initial boot seeds 90 days of synthetic cost data. Manual sync endpoints refresh a rolling 14-day window to simulate later AWS ingestion.
