"""Application audit events with deliberate redaction boundaries.

The audit table is an append-only application record.  It is intentionally
separate from request logging: callers choose the small, safe metadata payload
that is useful to an owner without persisting secrets or raw request bodies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


SENSITIVE_METADATA_KEYS = {
    "access_token",
    "authorization",
    "cookie",
    "credentials",
    "external_id",
    "id_token",
    "password",
    "refresh_token",
    "secret",
    "token",
    "token_hash",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_session_token",
    "external-id",
    "externalid",
}


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    if normalized in SENSITIVE_METADATA_KEYS:
        return True
    # Leave the deliberately safe `external_id_configured` boolean visible,
    # but treat unrecognized credential and token fields as secret by default.
    return (
        normalized.endswith("_token")
        or normalized.endswith("_secret")
        or normalized.endswith("_password")
        or normalized.endswith("_credential")
        or normalized in {"external_id", "externalid"}
    )


def redact_metadata(value: Any) -> Any:
    """Return JSON-safe audit metadata with known secret fields removed."""
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if _is_sensitive_key(key) else redact_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [redact_metadata(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def record_audit_event(
    session: Session,
    *,
    action: str,
    workspace_id: int | None,
    actor_user_id: int | None = None,
    connection_id: int | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: str = "success",
    request_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        request_id=request_id,
        metadata_json=redact_metadata(dict(metadata or {})),
    )
    session.add(event)
    return event
