# Infra Roadmap

This directory contains the platform layers that follow the local Compose MVP:

- `helm/aws-collaboration-dashboard`: local k3d application chart for web, API, PostgreSQL, and bootstrap migrations
- `opentofu`: infrastructure definitions for the Hetzner VPS, firewall, and DNS handoff

The Helm chart is intentionally local-first. Public k3s/VPS deployment, TLS, authentication, monitoring, and scheduled collection remain later phases.
