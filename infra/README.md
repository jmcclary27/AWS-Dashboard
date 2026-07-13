# Infra Roadmap

This directory contains the platform layers that follow the local Compose MVP:

- `helm/aws-collaboration-dashboard`: local k3d application chart for web, API, PostgreSQL, and bootstrap migrations
- `opentofu`: infrastructure definitions for the Hetzner VPS, firewall, and DNS handoff

The Helm chart is intentionally local-first. It exposes opt-in Cognito configuration for the authentication milestone, while public k3s/VPS deployment, TLS provisioning, monitoring, and scheduled collection remain later phases.

## Deferred platform milestones

Complete these after the authentication, authorization, connection ownership, and audit-log milestone.

### 1. Durable scheduled ingestion

- Move connection syncs out of the browser request path into durable background work.
- Add retry, idempotency, and non-overlapping execution per connection.
- Run scheduled collection through a Kubernetes CronJob and retain clear sync-run status and failure history.

### 2. Infrastructure as code and continuous delivery

- Replace the OpenTofu placeholder with one small public deployment environment: VPS, firewall, DNS/TLS handoff, and k3s prerequisites.
- Extend GitHub Actions from validation-only CI to build, publish, and deploy immutable image tags through Helm.
- Document deployment inputs, secret handling, health verification, and rollback.

### 3. Observability and recovery

- Add structured logs, metrics, and traces for the API, collectors, and scheduled jobs.
- Provide a Grafana dashboard for application and Kubernetes health, plus one actionable alert for failed scheduled collection.
- Define and test a PostgreSQL backup and restore procedure; keep the runbook with the deployment documentation.
