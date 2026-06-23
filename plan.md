# Multi-Account Cloud Cost Explorer
## Portfolio Project Plan (Cheap-First Kubernetes Learning Approach)

---

# Project Goal

Build a cloud cost analytics platform that aggregates AWS spending across multiple AWS accounts, visualizes trends, detects anomalies, and generates recommendations.

The project should:

- Demonstrate Kubernetes skills
- Demonstrate AWS knowledge
- Demonstrate backend engineering
- Demonstrate frontend engineering
- Demonstrate database design
- Demonstrate observability
- Demonstrate CI/CD

while remaining extremely inexpensive to build and operate.

---

# Key Design Philosophy

This project is intentionally built in stages.

Do NOT start with Kubernetes.

The goal is:

1. Build a working product
2. Validate business logic
3. Add Kubernetes where it provides value
4. Keep costs near zero

This mirrors how real engineering teams work.

---

# What Makes This Different Than AWS Cost Explorer?

AWS Cost Explorer focuses primarily on a single AWS organization.

This project focuses on:

- Multiple unrelated AWS accounts
- Team-level cost reporting
- Cross-account analytics
- Historical trend storage
- Custom recommendations
- Cost anomaly detection
- AI-generated insights (future)

Example:

```text
Account A (Personal)
Account B (Sandbox)
Account C (Production)

↓
Unified Dashboard

Total Monthly Spend:
$4,821

Engineering:
$3,210

Data Science:
$1,611
```

---

# Final Architecture

```text
                 +------------------+
                 |    Next.js UI    |
                 +---------+--------+
                           |
                           v
                 +------------------+
                 |    FastAPI API   |
                 +---------+--------+
                           |
                           v
                 +------------------+
                 |    PostgreSQL    |
                 +---------+--------+
                           ^
                           |
                 +---------+--------+
                 | Kubernetes       |
                 | CronJobs         |
                 +---------+--------+
                           |
                           v
                 +------------------+
                 | AWS Accounts     |
                 +------------------+
```

---

# Technology Stack

## Frontend

### Next.js

Purpose:

- Dashboard UI
- Cost reports
- Account management

### React

Purpose:

- Components
- State management

### Tailwind CSS

Purpose:

- Styling

### Recharts

Purpose:

- Cost visualizations

---

## Backend

### FastAPI

Purpose:

- REST API
- Business logic

### SQLAlchemy

Purpose:

- Database access

### Pydantic

Purpose:

- Validation

### Boto3

Purpose:

- AWS communication

---

## Database

### PostgreSQL

Purpose:

- Cost storage
- Historical analytics
- Recommendations
- Account metadata

---

## DevOps

### Docker

Purpose:

- Local development
- Containerization

### Docker Compose

Purpose:

- Cheap local development

### Kubernetes (k3d)

Purpose:

- Learn Kubernetes
- Local cluster

### Helm

Purpose:

- Kubernetes deployments

### GitHub Actions

Purpose:

- CI/CD

---

# Cost Strategy

## Development Phase

Everything runs locally.

Tools:

- Docker Desktop
- Docker Compose
- k3d

Cost:

```text
$0/month
```

---

## Initial Public Deployment

Single VPS:

Examples:

- DigitalOcean
- Hetzner
- Vultr

Run:

- k3s
- PostgreSQL
- FastAPI
- Next.js

Estimated Cost:

```text
$6-$12/month
```

---

## Avoid

Do NOT initially use:

- EKS
- RDS
- Managed Kubernetes
- Managed Postgres

These dramatically increase cost.

---

# Development Roadmap

---

# Phase 1: Local MVP

## Goal

Build a working application without Kubernetes.

---

## Architecture

```text
Next.js
    |
FastAPI
    |
PostgreSQL

All Managed Through Docker Compose
```

---

## Deliverables

### Frontend

Create pages:

- Dashboard
- Accounts
- Services
- Trends
- Recommendations

---

### Backend

Create APIs:

```text
GET /accounts
GET /summary
GET /services
GET /recommendations
POST /accounts
```

---

### Database

Create tables:

```text
accounts
daily_costs
service_costs
recommendations
anomalies
```

---

## Data Source

Use fake data.

Example:

```text
EC2      $450
S3       $120
Lambda   $40
RDS      $300
```

Purpose:

Build UI and backend before worrying about AWS.

---

## Expected Time

1-2 Weeks

---

## Cost

```text
$0
```

---

# Phase 2: Real AWS Integration

## Goal

Replace fake data with actual AWS cost data.

---

## AWS Services

Use:

### Cost Explorer

Retrieve:

- Daily spend
- Monthly spend
- Service breakdown

### STS

Assume read-only roles in other accounts.

---

## Flow

```text
Account Added
      |
Role ARN Stored
      |
Backend Assumes Role
      |
Cost Explorer Query
      |
Store Results
```

---

## Example IAM Permissions

```json
{
  "Effect": "Allow",
  "Action": [
    "ce:GetCostAndUsage",
    "ce:GetCostForecast",
    "ce:GetDimensionValues"
  ],
  "Resource": "*"
}
```

---

## Deliverables

Users can:

- Connect AWS account
- View costs
- View service breakdowns

---

## Expected Time

1 Week

---

## Cost

```text
Typically less than $1/month
```

---

# Phase 3: Historical Analytics

## Goal

Store data over time.

---

## Features

### Daily Trends

```text
Last 30 Days
Last 90 Days
Last 12 Months
```

### Service Trends

```text
EC2 Growth
S3 Growth
Lambda Growth
```

### Forecasting

Use:

```text
AWS Cost Forecast API
```

---

## Deliverables

Historical reporting dashboard.

---

## Expected Time

1 Week

---

## Cost

```text
Near $0
```

---

# Phase 4: Kubernetes Migration

## Goal

Introduce Kubernetes after the application works.

---

## Install

### Local Cluster

Use:

```bash
k3d cluster create cloud-cost
```

---

## Deploy Components

### Backend

Deployment

Service

---

### Frontend

Deployment

Service

---

### PostgreSQL

StatefulSet

PersistentVolume

---

### Configuration

ConfigMaps

Secrets

---

## Deliverables

Fully functioning Kubernetes deployment.

---

## Expected Time

1 Week

---

## Cost

```text
$0
```

Local cluster only.

---

# Phase 5: Kubernetes CronJobs

## Goal

Use Kubernetes for scheduled collection.

---

## Replace

Replace backend scheduler.

---

## Add

```yaml
CronJob
```

Runs:

```text
Every Night
```

Process:

```text
Assume Role
↓
Collect Costs
↓
Store Costs
↓
Run Anomaly Detection
```

---

## Deliverables

Real Kubernetes workload orchestration.

---

## Expected Time

3-5 Days

---

## Cost

```text
$0
```

---

# Phase 6: Helm

## Goal

Package application professionally.

---

## Create

```text
charts/
  cloud-cost-explorer/
```

---

## Deploy

```bash
helm install cloud-cost .
```

---

## Deliverables

Reusable Kubernetes deployments.

---

## Expected Time

2-3 Days

---

# Phase 7: Monitoring

## Goal

Learn observability.

---

## Add

### Prometheus

Metrics collection

### Grafana

Visualization

---

## Monitor

### Infrastructure

- CPU
- Memory
- Pods

### Application

- API latency
- Request count
- CronJob duration
- Collection failures

---

## Expected Time

3-5 Days

---

## Cost

```text
$0
```

---

# Phase 8: Recommendations Engine

## Goal

Generate actionable cost recommendations.

---

## Rule-Based Recommendations

Examples:

```text
EC2 spend increased 35%
```

```text
S3 storage grew continuously
for 30 days
```

```text
Lambda costs doubled this week
```

---

## Estimated Savings

Provide:

```text
Potential Savings:
$150/month
```

---

## Future Enhancement

Optional:

Use an LLM API to generate:

```text
Executive Summary
```

from collected cost data.

---

## Expected Time

1 Week

---

# Phase 9: Public Deployment

## Goal

Make project publicly accessible.

---

## Infrastructure

Single VPS

Run:

```text
k3s
PostgreSQL
FastAPI
Next.js
Prometheus
Grafana
```

on one machine.

---

## Monthly Cost

```text
VPS              $6-$12
Domain           $1-$2
AWS API Usage    <$1
```

Expected Total:

```text
$7-$15/month
```

---

# Resume Description

Built a Kubernetes-native cloud cost analytics platform that aggregates AWS spending across multiple accounts using IAM role federation and Cost Explorer APIs. Designed scheduled ingestion pipelines with Kubernetes CronJobs, implemented anomaly detection and cost optimization recommendations, deployed a full-stack architecture using FastAPI, PostgreSQL, Next.js, Helm, Prometheus, Grafana, and GitHub Actions, and maintained development costs near zero through local Kubernetes environments.