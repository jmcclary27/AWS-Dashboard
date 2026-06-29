# Local Setup

## Compose path

1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Visit `http://localhost:3000`.

## Real AWS path

Use this only when you want real org-management or standalone account-role data.

1. Authenticate on the host with short-lived credentials or an AWS profile.
2. Set `AWS_PROFILE` in `.env`.
3. Set `AWS_CONFIG_DIR` in `.env` to your host AWS config directory.
4. Start the stack with `docker compose -f docker-compose.yml -f docker-compose.aws.yml up --build`.
5. Open `Settings` and confirm the `AWS runtime` panel shows a verified caller identity.
6. If you want exact payable billing truth, configure the connection with an AWS Data Exports bucket, prefix, and region that the assumed role can read.
7. Create or update your connection, then run `Validate Access` before `Sync`.

Security notes:

- Prefer a read-only mount of `~/.aws` over long-lived static keys.
- If you must use environment credentials, keep them short-lived and only pass them to the `api` service.
- Do not paste AWS access keys into the app UI. The UI only stores connection metadata such as role ARN, external ID, billing view ARN, and optional AWS Data Exports location details.

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

The initial boot seeds 90 days of synthetic cost data into the built-in demo connection.

- The web app now scopes every analytics request by `connection_id`.
- The settings page is the primary UI for creating org-management and standalone account-role connections.
- The dashboard now prefers payable bill truth for month-to-date and projected month-end totals, while services, trends, anomalies, and recommendations stay on the usage analytics layer.
- Demo sync continues to refresh a rolling 14-day window so local work stays near-zero cost even before AWS credentials are configured.
