# Local Kubernetes deployment

This guide deploys the dashboard to a local k3d cluster using the Helm chart. It is a single-node development environment, not a public or production deployment.

## Prerequisites

- Docker Desktop running
- `kubectl`, Helm, and k3d installed and on `PATH`
- An unused host port `8080`

## Build and deploy

Build the local images from the repository root. The web build argument is compiled into browser JavaScript, so it must use the same-origin API path used by the Ingress.

```powershell
docker build -t aws-dashboard-api:local -f apps/api/Dockerfile .
docker build --build-arg NEXT_PUBLIC_API_BASE_URL=/api/v1 --build-arg NEXT_PUBLIC_AUTH_ENABLED=false -t aws-dashboard-web:local -f apps/web/Dockerfile .

k3d cluster create cloud-cost --agents 1 -p "8080:80@loadbalancer"
k3d image import -c cloud-cost aws-dashboard-api:local aws-dashboard-web:local

helm upgrade --install aws-dashboard infra/helm/aws-collaboration-dashboard --namespace aws-dashboard --create-namespace --values infra/helm/aws-collaboration-dashboard/values-local.yaml --wait --wait-for-jobs --timeout 5m
```

Open `http://dashboard.localhost:8080`. Traefik routes `/api` to FastAPI and all other paths to Next.js. The chart also includes a hostless fallback at `http://localhost:8080` for Windows environments where the `.localhost` hostname is not resolved by the local DNS configuration.

If another local service already owns port `8080`, choose an unused host port when creating the cluster, for example `-p "18080:80@loadbalancer"`, and substitute that port in the URLs above. The Helm chart itself does not need to change.

The chart uses a normal, revision-named bootstrap Job instead of a Helm migration hook. This lets `helm upgrade --install --wait --wait-for-jobs` wait for PostgreSQL, migrations, and demo seeding without racing API startup.

## Cognito (optional)

The local chart defaults to `auth.enabled: false`, which is the intended k3d demo path. The `dashboard.localhost` ingress is plain HTTP, while Cognito requires HTTPS for non-local callback hosts, so use Docker Compose on `http://localhost:3000` for local Cognito experiments or provide a TLS-enabled public host for an authenticated Helm deployment.

For an authenticated deployment, create a private values file with `auth.enabled`, `auth.publicAppUrl`, `api.corsOrigins`, `auth.cognito`, and, only when migrating existing non-demo data, `auth.bootstrapOwner`. Build the web image with the matching browser flag before importing it:

```powershell
docker build --build-arg NEXT_PUBLIC_API_BASE_URL=/api/v1 --build-arg NEXT_PUBLIC_AUTH_ENABLED=true -t aws-dashboard-web:local -f apps/web/Dockerfile .
```

The callback and logout URLs in `auth.cognito` must match the public ingress host exactly. Cognito uses a public PKCE client; do not put a client secret in Helm values. The chart gives the API its verifier and user-info settings, the web server its Managed Login settings, and the bootstrap Job only the migration-owner and issuer inputs. See [Cognito authentication and workspace access](authentication.md) for the full rollout sequence.

## Real AWS credentials

The default deployment works with seeded demo data. To validate real AWS connections and run manual syncs, create a Kubernetes Secret containing temporary standard AWS environment credentials before installing or upgrading the chart.

```powershell
kubectl create namespace aws-dashboard --dry-run=client -o yaml | kubectl apply -f -
kubectl -n aws-dashboard create secret generic aws-runtime --from-literal=AWS_ACCESS_KEY_ID=<temporary-access-key> --from-literal=AWS_SECRET_ACCESS_KEY=<temporary-secret> --from-literal=AWS_SESSION_TOKEN=<temporary-session-token> --from-literal=AWS_REGION=us-east-1 --from-literal=AWS_DEFAULT_REGION=us-east-1

helm upgrade --install aws-dashboard infra/helm/aws-collaboration-dashboard --namespace aws-dashboard --values infra/helm/aws-collaboration-dashboard/values-local.yaml --set aws.existingSecret=aws-runtime --wait --wait-for-jobs --timeout 5m
```

Do not commit credentials, add them to Helm values files, or include `AWS_PROFILE` in this Secret. The chart injects the existing Secret only into the API pod. Refreshing credentials requires updating the Secret and restarting the API Deployment:

```powershell
kubectl -n aws-dashboard rollout restart deployment/aws-dashboard-api
```

The source identity needs STS access and permission to assume any configured connection role. The assumed role needs Cost Explorer read access in `us-east-1`; AWS Data Exports access is optional and only required for exact payable-billing truth.

## Smoke test and upgrade check

```powershell
kubectl -n aws-dashboard get pods,jobs,pvc
Invoke-WebRequest http://localhost:8080/api/v1/me

kubectl -n aws-dashboard port-forward service/aws-dashboard-api 8000:8000
# In another terminal:
Invoke-WebRequest http://localhost:8000/health
Invoke-WebRequest http://localhost:8000/ready
```

In the dashboard, select a workspace and open **Settings**. As an owner or editor, validate and manually sync a real connection. The API records the sync result in the persistent PostgreSQL volume.

Run a second Helm upgrade with the same values and confirm the PVC stays bound and the bootstrap Job completes again. `--reuse-values` preserves `aws.existingSecret` when it was supplied on the original install:

```powershell
helm upgrade aws-dashboard infra/helm/aws-collaboration-dashboard --namespace aws-dashboard --values infra/helm/aws-collaboration-dashboard/values-local.yaml --reuse-values --wait --wait-for-jobs --timeout 5m
kubectl -n aws-dashboard get pvc,jobs
```

The chart deliberately does not include a collector CronJob, public TLS provisioning, monitoring, or public-VPS provisioning. PostgreSQL storage is retained for local inspection; remove the PVC manually when you intentionally want to reset the database.
