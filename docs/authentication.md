# Cognito authentication and workspace access

The application uses Amazon Cognito Managed Login with the OAuth 2.0 authorization-code flow and PKCE. The browser never stores an access token or refresh token in JavaScript: the Next.js auth handlers keep both in secure, HTTP-only cookies, and use a separate double-submit CSRF cookie for mutations. FastAPI is the authorization boundary. It verifies Cognito access-token signatures against JWKS, validates issuer, expiration, token use, and app-client ID, then applies workspace roles before loading a connection.

## Create Cognito resources

Create a separate user pool and Managed Login domain for each environment. In the Cognito console:

1. Enable self-service sign-up and require verified email addresses.
2. Create a **public** app client with no client secret.
3. Enable authorization-code flow with PKCE and the `openid`, `email`, and `profile` scopes.
4. Configure the Managed Login domain and register exact callback and sign-out URLs:
   - local Compose: `http://localhost:3000/auth/callback` and `http://localhost:3000/`
   - deployed environment: `https://<public-host>/auth/callback` and `https://<public-host>/`
5. Keep social providers and application-managed passwords out of this milestone.

Use HTTPS for every non-local callback or logout URL. Cognito configuration details are covered in AWS's [PKCE guide](https://docs.aws.amazon.com/cognito/latest/developerguide/using-pkce-in-authorization-code.html) and [token-verification guide](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html).

## Configure the application

Start from `.env.example`. The local demo remains intentionally open with both flags set to `false`. To enable Cognito, set both values to `true`, then rebuild the web image because `NEXT_PUBLIC_AUTH_ENABLED` is compiled into browser JavaScript.

```dotenv
AUTH_ENABLED=true
NEXT_PUBLIC_AUTH_ENABLED=true
PUBLIC_APP_URL=https://dashboard.example.com
CORS_ORIGINS=https://dashboard.example.com

COGNITO_DOMAIN=your-prefix.auth.us-east-1.amazoncognito.com
COGNITO_CLIENT_ID=<public-app-client-id>
COGNITO_APP_CLIENT_ID=<same-public-app-client-id>
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_example
COGNITO_REDIRECT_URI=https://dashboard.example.com/auth/callback
COGNITO_LOGOUT_URI=https://dashboard.example.com/
COGNITO_SCOPES=openid email profile
```

`COGNITO_CLIENT_ID` is used by Next.js and `COGNITO_APP_CLIENT_ID` is used by FastAPI; they must contain the same public client ID. FastAPI derives the issuer and JWKS endpoint from `COGNITO_REGION` and `COGNITO_USER_POOL_ID` unless `COGNITO_ISSUER` or `COGNITO_JWKS_URL` is set explicitly. It uses the Managed Login `userinfo` endpoint to enrich access-token identities with verified email; set `COGNITO_USERINFO_URL` only to override the standard endpoint derived from `COGNITO_DOMAIN`.

No Cognito client secret belongs in this repository, Helm values, or container environment. The app client is deliberately public because PKCE protects the authorization-code exchange.

Keep the web app and API on the same public host (the Helm ingress uses `/api` for FastAPI). Session cookies are host-scoped; a deployment that sends browser requests to a separate `api.` host needs an explicit shared-cookie-domain design before it can use this flow safely.

`AUTH_COOKIE_SECURE=false` is valid only for an explicit `http://localhost`, `127.0.0.1`, or `::1` callback during local development. A non-loopback production callback always uses Secure cookies, regardless of that setting.

## Existing-database rollout

Before applying the tenancy migration to a database that already has non-demo connections:

1. Take a `pg_dump`.
2. Create the intended owner in Cognito and obtain that user's `sub` and verified email.
3. Set the bootstrap values below in deployment configuration.
4. Apply migrations and deploy the API and web image together.

```dotenv
AUTH_BOOTSTRAP_OWNER_SUB=<cognito-sub>
AUTH_BOOTSTRAP_OWNER_EMAIL=owner@example.com
# Optional when COGNITO_ISSUER is already set.
AUTH_BOOTSTRAP_OWNER_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example
AUTH_BOOTSTRAP_WORKSPACE_NAME=Bootstrap Workspace
```

The migration moves synthetic demo data to the system-owned **Demo Workspace**. It moves every existing non-demo connection to the named bootstrap owner's workspace and stops before changing the schema if that owner configuration is absent. It does not guess an owner. For this migration, provide `AUTH_BOOTSTRAP_OWNER_ISSUER`, an explicit `COGNITO_ISSUER`, or both `COGNITO_REGION` and `COGNITO_USER_POOL_ID`; the last option derives the same concrete issuer that Cognito uses. New users receive a personal owner workspace on their first authenticated API call; the Demo Workspace is virtual read-only viewer access for every signed-in user.

## Docker Compose

Copy the example environment file, populate the Cognito section, and rebuild both services:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The Compose file supplies bootstrap-owner and issuer inputs only to the one-shot bootstrap container, backend verification values only to FastAPI, and Managed Login settings only to the Next.js container. It also rebuilds the web app with `NEXT_PUBLIC_AUTH_ENABLED`; changing this flag without `--build` leaves the previous browser behavior in the image.

## Helm and k3d

The chart defaults to `auth.enabled: false`. For an authenticated image, build the web image with matching browser configuration before importing it into k3d:

```powershell
docker build --build-arg NEXT_PUBLIC_API_BASE_URL=/api/v1 --build-arg NEXT_PUBLIC_AUTH_ENABLED=true -t aws-dashboard-web:local -f apps/web/Dockerfile .
```

In a private values file, set `auth.enabled`, `auth.publicAppUrl`, `api.corsOrigins`, `auth.cognito`, and, only for the existing-data migration, `auth.bootstrapOwner`. The app client ID is public configuration; do not add a client secret. The callback and logout values must match the ingress host exactly. The chart injects the settings into the API, web server, and bootstrap Job as appropriate.

## Smoke test

After deployment, complete this sequence with two Cognito users:

1. Sign in and confirm a personal workspace is selected.
2. Create a connection, validate it, and request a manual sync as an editor or owner.
3. Create a seven-day invite, accept it with the email-bound second account, and verify the selected role.
4. Confirm viewers cannot modify, sync, share, or inspect audit history; cross-workspace connection URLs return `404`.
5. Inspect owner-only audit history, then log out and confirm the session cookies no longer authorize API calls.
