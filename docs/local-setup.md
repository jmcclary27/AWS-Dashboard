# Local Setup

## Compose path

1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Visit `http://localhost:3000`.

The default Compose environment keeps `AUTH_ENABLED=false` and opens the seeded Demo Workspace through the local development identity. This is for self-contained development only. For a local Cognito test, configure the local callback and logout URLs in Cognito, set both `AUTH_ENABLED=true` and `NEXT_PUBLIC_AUTH_ENABLED=true`, populate the Cognito variables, and rerun `docker compose up --build`. See [Cognito authentication and workspace access](authentication.md) for the complete setup and migration rollout requirements.

## Real AWS path

Use this only when you want real org-management or standalone account-role data.

1. Authenticate on the host with short-lived credentials or an AWS profile.
2. Set `AWS_PROFILE` in `.env`.
3. Set `AWS_CONFIG_DIR` in `.env` to your host AWS config directory.
4. Start the stack with `docker compose -f docker-compose.yml -f docker-compose.aws.yml up --build`.
5. Select a workspace, then open `Settings` as an owner or editor.
6. If you want exact payable billing truth, configure the connection with an AWS Data Exports bucket, prefix, and region that the assumed role can read.
7. Create or update your connection, then run `Validate Access` before requesting `Sync`.

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

The initial boot seeds 90 days of synthetic cost data into the built-in Demo Workspace and connection.

- Every signed-in user has virtual viewer access to the Demo Workspace; it is read-only and cannot be synced, shared, or audited by normal users.
- The web app scopes analytics by an authorized `connection_id` and its selected workspace.
- The settings page is the primary UI for owners and editors to create org-management and standalone account-role connections.
- The dashboard now prefers payable bill truth for month-to-date and projected month-end totals, while services, trends, anomalies, and recommendations stay on the usage analytics layer.
- Demo data is seeded during bootstrap so local work stays near-zero cost even before AWS credentials are configured; normal users cannot request demo syncs.

## Local Kubernetes path

For the Helm and k3d deployment path, including image import, ingress, bootstrap migrations, AWS Secret handling, and the manual smoke test, see [Local Kubernetes deployment](kubernetes-local.md).
