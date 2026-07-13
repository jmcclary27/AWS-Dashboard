from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


WorkspaceRole = Literal["owner", "editor", "viewer"]
InviteRole = Literal["editor", "viewer"]


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("A valid email address is required")
    return normalized


class WorkspaceInviteCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: InviteRole

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class WorkspaceMemberPatch(BaseModel):
    role: InviteRole


class InviteAccept(BaseModel):
    token: str = Field(min_length=24, max_length=512)


class AuditEventItem(BaseModel):
    id: int
    action: str
    outcome: str
    target_type: str | None = None
    target_id: str | None = None
    connection_id: int | None = None
    actor_name: str | None = None
    request_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
