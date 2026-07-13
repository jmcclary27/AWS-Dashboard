"""Authenticated API routes for the connection-scoped dashboard.

The browser may choose a workspace or connection id, but it never gets to
decide whether it may use it.  Every route resolves that choice through the
workspace authorization helpers before querying analytics or AWS settings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    Principal,
    get_authorized_connection,
    get_current_principal,
    require_csrf,
    require_workspace_role,
    request_id_for,
)
from app.config import get_settings
from app.db.models import (
    Account,
    AuditEvent,
    Connection,
    ConnectionAccount,
    SyncRun,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
    utcnow,
)
from app.db.seed import ensure_connection_membership, ensure_demo_workspace
from app.db.session import get_db
from app.schemas.api import ConnectionCreate, ConnectionPatch, SyncRequest, SyncResponse
from app.schemas.tenancy import InviteAccept, WorkspaceInviteCreate, WorkspaceMemberPatch
from app.services.audit import record_audit_event
from app.services.aws_access import validate_connection_access
from app.services.analytics import (
    build_accounts_response,
    build_billing_overview_response,
    build_forecast_response,
    build_services_response,
    build_summary_response,
    build_trends_response,
    list_anomalies_response,
    list_connections_response,
    list_recommendations_response,
)
from app.services.collectors import CollectorExecutionError, sync_connection


router = APIRouter()


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _connection_config(connection: Connection) -> dict:
    """Editor-only connection configuration; external IDs stay write-only."""
    return {
        "id": connection.id,
        "workspace_id": connection.workspace_id,
        "name": connection.name,
        "kind": connection.kind,
        "enabled": connection.enabled,
        "role_arn": connection.role_arn,
        "external_id_configured": bool(connection.external_id),
        "billing_view_arn": connection.billing_view_arn,
        "billing_mode": connection.billing_mode,
        "billing_export_bucket": connection.billing_export_bucket,
        "billing_export_prefix": connection.billing_export_prefix,
        "billing_export_region": connection.billing_export_region,
        "team_tag_key": connection.team_tag_key,
        "created_by_user_id": connection.created_by_user_id,
        "created_at": connection.created_at.isoformat() if connection.created_at else None,
        "updated_at": connection.updated_at.isoformat() if connection.updated_at else None,
    }


def _sync_response_for(connection: Connection, result) -> dict:
    if result.status in {"success", "partial_success"}:
        message = "Sync completed."
    else:
        message = "Sync did not complete. Revalidate connection access and retry."
    return {
        "status": result.status,
        "connection_id": connection.id,
        "accounts_synced": result.accounts_synced,
        "records_written": result.records_written,
        "window_days": result.window_days,
        # Collector/provider text is intentionally not reflected. It can
        # contain request context on some SDK failures; safe event metadata and
        # the protected audit trail carry the operational result instead.
        "message": message,
    }


def _request_id(request: Request) -> str:
    return request_id_for(request)


def _record_denied_connection_access(
    db: Session,
    *,
    principal: Principal,
    connection_id: int,
    action: str,
    request: Request,
) -> None:
    """Best-effort denied-access audit without changing the caller's error."""
    connection = db.get(Connection, connection_id)
    if not connection or not connection.workspace_id:
        return
    try:
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            action=action,
            target_type="connection",
            target_id=str(connection.id),
            outcome="denied",
            request_id=_request_id(request),
            metadata={"reason": "authorization"},
        )
        db.commit()
    except Exception:
        db.rollback()


def _authorized_connection(
    db: Session,
    principal: Principal,
    connection_id: int,
    minimum_role: str,
    request: Request,
    action: str,
) -> Connection:
    try:
        return get_authorized_connection(db, principal, connection_id, minimum_role)  # type: ignore[arg-type]
    except HTTPException as error:
        if error.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND}:
            _record_denied_connection_access(
                db,
                principal=principal,
                connection_id=connection_id,
                action=action,
                request=request,
            )
        raise


def _mutable_connection(
    db: Session,
    principal: Principal,
    connection_id: int,
    request: Request,
    action: str,
) -> Connection:
    connection = _authorized_connection(db, principal, connection_id, "editor", request, action)
    if connection.kind == "demo":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Demo connections are read-only")
    return connection


def _authorized_workspace(
    db: Session,
    principal: Principal,
    workspace_id: int,
    minimum_role: str,
    request: Request,
    action: str,
):
    try:
        return require_workspace_role(db, principal, workspace_id, minimum_role)  # type: ignore[arg-type]
    except HTTPException as error:
        workspace = db.get(Workspace, workspace_id)
        if workspace and error.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND}:
            try:
                record_audit_event(
                    db,
                    actor_user_id=principal.user_id,
                    workspace_id=workspace.id,
                    action=action,
                    target_type="workspace",
                    target_id=str(workspace.id),
                    outcome="denied",
                    request_id=_request_id(request),
                    metadata={"reason": "authorization"},
                )
                db.commit()
            except Exception:
                db.rollback()
        raise


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive timestamps while retaining PostgreSQL offsets."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _active_invitation(invitation: WorkspaceInvitation, now: datetime) -> bool:
    return (
        invitation.accepted_at is None
        and invitation.revoked_at is None
        and _as_utc(invitation.expires_at) > _as_utc(now)
    )


@router.get("/me")
def get_me(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)) -> dict:
    user = db.get(User, principal.user_id)
    memberships = db.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(WorkspaceMembership.user_id == principal.user_id, Workspace.is_demo.is_(False))
        .order_by(Workspace.name)
    ).all()
    # Bootstrap normally creates this row, but persisting it here as well
    # keeps a first authenticated request usable against a newly initialized
    # schema (for example a preview environment before demo data is loaded).
    demo_workspace = ensure_demo_workspace(db)
    db.commit()
    return {
        "user": {
            "id": principal.user_id,
            "email": principal.email or (user.email if user else None),
            "display_name": principal.display_name or (user.display_name if user else "User"),
        },
        "workspaces": [
            {
                "id": workspace.id,
                "name": workspace.name,
                "role": membership.role,
                "is_demo": False,
                "read_only": False,
            }
            for membership, workspace in memberships
        ]
        + [
            {
                "id": demo_workspace.id,
                "name": demo_workspace.name,
                "role": "viewer",
                "is_demo": True,
                "read_only": True,
            }
        ],
    }


@router.get("/connections")
def list_connections(
    request: Request,
    workspace_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    access = _authorized_workspace(db, principal, workspace_id, "viewer", request, "connection.list")
    payload = list_connections_response(db, access.workspace.id)
    payload["workspace_id"] = access.workspace.id
    payload["role"] = access.role
    payload["read_only"] = access.is_demo
    return payload


@router.get("/connections/{connection_id}")
def get_connection(
    connection_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "editor", request, "connection.read_config")
    return {"item": _connection_config(connection)}


@router.post("/connections", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_connection(
    payload: ConnectionCreate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    access = _authorized_workspace(db, principal, payload.workspace_id, "editor", request, "connection.create")
    connection = Connection(
        workspace_id=access.workspace.id,
        created_by_user_id=principal.user_id,
        name=payload.name,
        kind=payload.kind,
        enabled=payload.enabled,
        role_arn=payload.role_arn,
        external_id=payload.external_id,
        billing_view_arn=payload.billing_view_arn,
        billing_mode=payload.billing_mode,
        billing_export_bucket=payload.billing_export_bucket,
        billing_export_prefix=payload.billing_export_prefix,
        billing_export_region=payload.billing_export_region,
        team_tag_key=payload.team_tag_key,
    )
    db.add(connection)
    try:
        db.flush()
        if payload.kind == "account_role" and payload.account:
            account = db.execute(
                select(Account).where(Account.aws_account_id == payload.account.aws_account_id)
            ).scalar_one_or_none()
            if not account:
                # Account is a canonical reference row. Connection-specific
                # credentials intentionally remain on Connection.
                account = Account(
                    display_name=payload.account.display_name,
                    aws_account_id=payload.account.aws_account_id,
                    team_tag_key=payload.team_tag_key,
                    enabled=True,
                )
                db.add(account)
                db.flush()
            ensure_connection_membership(
                db,
                connection_id=connection.id,
                account_id=account.id,
                membership_source="manual",
                is_primary=True,
                enabled=True,
            )
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            action="connection.created",
            target_type="connection",
            target_id=str(connection.id),
            request_id=_request_id(request),
            metadata={"kind": connection.kind, "name": connection.name, "external_id_configured": bool(connection.external_id)},
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A connection with that name already exists") from error
    db.refresh(connection)
    return {"item": _connection_config(connection)}


@router.patch("/connections/{connection_id}", dependencies=[Depends(require_csrf)])
def update_connection(
    connection_id: int,
    payload: ConnectionPatch,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _mutable_connection(db, principal, connection_id, request, "connection.update")
    updates = payload.model_dump(exclude_unset=True)
    account_payload = updates.pop("account", None)
    safe_fields = []
    for field, value in updates.items():
        setattr(connection, field, value)
        safe_fields.append("external_id_configured" if field == "external_id" else field)

    if connection.kind == "account_role":
        if not connection.role_arn:
            raise bad_request("role_arn is required for account_role connections")
        if account_payload:
            account = db.execute(
                select(Account).where(Account.aws_account_id == account_payload["aws_account_id"])
            ).scalar_one_or_none()
            if not account:
                account = Account(
                    display_name=account_payload["display_name"],
                    aws_account_id=account_payload["aws_account_id"],
                    team_tag_key=connection.team_tag_key,
                    enabled=True,
                )
                db.add(account)
                db.flush()
            memberships = db.scalars(
                select(ConnectionAccount).where(ConnectionAccount.connection_id == connection.id)
            ).all()
            for membership in memberships:
                membership.is_primary = False
                db.add(membership)
            ensure_connection_membership(
                db,
                connection_id=connection.id,
                account_id=account.id,
                membership_source="manual",
                is_primary=True,
                enabled=True,
            )
            safe_fields.append("primary_account")
    elif account_payload:
        raise bad_request("Only account_role connections accept account updates")

    try:
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            action="connection.updated",
            target_type="connection",
            target_id=str(connection.id),
            request_id=_request_id(request),
            metadata={"fields": sorted(set(safe_fields))},
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A connection with that name already exists") from error
    db.refresh(connection)
    return {"item": _connection_config(connection)}


@router.post("/connections/{connection_id}/validate", dependencies=[Depends(require_csrf)])
def validate_connection(
    connection_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _mutable_connection(db, principal, connection_id, request, "connection.validate")
    try:
        result = validate_connection_access(db, connection)
        outcome = "success" if result.get("ready") else "failed"
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            action="connection.validated",
            target_type="connection",
            target_id=str(connection.id),
            outcome=outcome,
            request_id=_request_id(request),
            metadata={"ready": bool(result.get("ready")), "truth_mode": result.get("truth_mode")},
        )
        db.commit()
        return result
    except HTTPException:
        raise
    except Exception as error:
        db.rollback()
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            action="connection.validated",
            target_type="connection",
            target_id=str(connection.id),
            outcome="failed",
            request_id=_request_id(request),
            metadata={"reason": type(error).__name__},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Connection validation failed") from error


@router.post("/connections/{connection_id}/sync", response_model=SyncResponse, dependencies=[Depends(require_csrf)])
def sync_selected_connection(
    connection_id: int,
    request: Request,
    payload: SyncRequest | None = Body(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _mutable_connection(db, principal, connection_id, request, "connection.sync")
    requested_days = payload.days if payload else None
    # Keep the intent independently auditable even though the current collector
    # executes inline. A later durable worker can preserve this event as the
    # enqueue boundary without changing the audit contract.
    record_audit_event(
        db,
        actor_user_id=principal.user_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        action="connection.sync_requested",
        target_type="connection",
        target_id=str(connection.id),
        request_id=_request_id(request),
        metadata={"window_days": requested_days},
    )
    db.commit()
    try:
        result = sync_connection(db, connection, days=requested_days)
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            action="connection.sync_completed",
            target_type="connection",
            target_id=str(connection.id),
            outcome=result.status,
            request_id=_request_id(request),
            metadata={"window_days": result.window_days, "records_written": result.records_written},
        )
        db.commit()
        return _sync_response_for(connection, result)
    except CollectorExecutionError as error:
        db.rollback()
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            action="connection.sync_completed",
            target_type="connection",
            target_id=str(connection.id),
            outcome="failed",
            request_id=_request_id(request),
            metadata={"reason": "collector_error"},
        )
        db.commit()
        # Do not reflect collector/provider messages. Even normalized SDK
        # failures can grow new request context over time, while this response
        # must never expose an external ID or credential material.
        raise bad_request("Connection sync failed. Revalidate connection access and retry.") from error
    except Exception as error:
        db.rollback()
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            action="connection.sync_completed",
            target_type="connection",
            target_id=str(connection.id),
            outcome="failed",
            request_id=_request_id(request),
            metadata={"reason": type(error).__name__},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Connection sync failed") from error


@router.get("/sync-runs")
def list_sync_runs(
    request: Request,
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "sync_run.list")
    runs = db.scalars(
        select(SyncRun)
        .where(SyncRun.connection_id == connection.id)
        .order_by(SyncRun.finished_at.desc(), SyncRun.started_at.desc())
        .limit(50)
    ).all()
    return {
        "connection_id": connection.id,
        "items": [
            {
                "id": run.id,
                "status": run.status,
                "kind": run.sync_type,
                "message": (
                    "Sync completed."
                    if run.status in {"success", "partial_success"}
                    else "Sync did not complete. Revalidate connection access and retry."
                )
                if run.message
                else None,
                "window_days": run.window_days,
                "accounts_synced": run.accounts_synced,
                "records_written": run.records_written,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
            for run in runs
        ],
    }


@router.get("/accounts")
def list_accounts(
    request: Request,
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "account.list")
    return build_accounts_response(db, connection.id)


@router.get("/billing/overview")
def get_billing_overview(
    request: Request,
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "billing.read")
    return build_billing_overview_response(db, connection.id)


@router.get("/summary")
def get_summary(
    request: Request,
    range: str = Query("30d"),
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "summary.read")
    try:
        return build_summary_response(db, connection.id, range)
    except ValueError as error:
        raise bad_request(str(error)) from error


@router.get("/services")
def get_services(
    request: Request,
    range: str = Query("30d"),
    account_id: int | None = Query(default=None),
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "services.read")
    try:
        return build_services_response(db, connection.id, range, account_id)
    except ValueError as error:
        raise bad_request(str(error)) from error


@router.get("/trends")
def get_trends(
    request: Request,
    range: str = Query("90d"),
    group_by: str = Query("account"),
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "trends.read")
    try:
        return build_trends_response(db, connection.id, range, group_by)
    except ValueError as error:
        raise bad_request(str(error)) from error


@router.get("/forecast")
def get_forecast(
    request: Request,
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "forecast.read")
    return build_forecast_response(db, connection.id)


@router.get("/recommendations")
def get_recommendations(
    request: Request,
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "recommendations.read")
    return list_recommendations_response(db, connection.id)


@router.get("/anomalies")
def get_anomalies(
    request: Request,
    connection_id: int = Query(..., gt=0),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    connection = _authorized_connection(db, principal, connection_id, "viewer", request, "anomalies.read")
    return list_anomalies_response(db, connection.id)


@router.get("/workspaces/{workspace_id}/members")
def list_workspace_members(
    workspace_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    access = _authorized_workspace(db, principal, workspace_id, "owner", request, "workspace.members.list")
    rows = db.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.workspace_id == access.workspace.id)
        .order_by(WorkspaceMembership.role.desc(), User.email)
    ).all()
    return {
        "workspace_id": access.workspace.id,
        "items": [
            {
                "user_id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "role": membership.role,
                "created_at": membership.created_at.isoformat() if membership.created_at else None,
            }
            for membership, user in rows
        ],
    }


@router.post("/workspaces/{workspace_id}/invites", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_workspace_invite(
    workspace_id: int,
    payload: WorkspaceInviteCreate,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    access = _authorized_workspace(db, principal, workspace_id, "owner", request, "workspace.invite.create")
    now = utcnow()
    existing = db.scalars(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.workspace_id == access.workspace.id,
            WorkspaceInvitation.email == payload.email,
        )
    ).all()
    if any(_active_invitation(invitation, now) for invitation in existing):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An active invitation already exists for that email")

    raw_token = token_urlsafe(32)
    invitation = WorkspaceInvitation(
        workspace_id=access.workspace.id,
        email=payload.email,
        role=payload.role,
        token_hash=sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=now + timedelta(days=7),
        invited_by_user_id=principal.user_id,
    )
    db.add(invitation)
    db.flush()
    record_audit_event(
        db,
        actor_user_id=principal.user_id,
        workspace_id=access.workspace.id,
        action="workspace.invite_created",
        target_type="invitation",
        target_id=str(invitation.id),
        request_id=_request_id(request),
        metadata={"email": invitation.email, "role": invitation.role, "expires_at": invitation.expires_at.isoformat()},
    )
    db.commit()
    settings = get_settings()
    base_url = settings.public_app_url.rstrip("/")
    return {
        "item": {
            "id": invitation.id,
            "email": invitation.email,
            "role": invitation.role,
            "expires_at": invitation.expires_at.isoformat(),
            "invite_url": f"{base_url}/invite?token={raw_token}",
        }
    }


@router.get("/workspaces/{workspace_id}/invites")
def list_workspace_invites(
    workspace_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    """List invite lifecycle state without ever returning a raw invite token."""
    access = _authorized_workspace(db, principal, workspace_id, "owner", request, "workspace.invite.list")
    now = utcnow()
    invitations = db.scalars(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.workspace_id == access.workspace.id)
        .order_by(WorkspaceInvitation.created_at.desc(), WorkspaceInvitation.id.desc())
        .limit(100)
    ).all()
    return {
        "workspace_id": access.workspace.id,
        "items": [
            {
                "id": invitation.id,
                "email": invitation.email,
                "role": invitation.role,
                "status": (
                    "accepted"
                    if invitation.accepted_at
                    else "revoked"
                    if invitation.revoked_at
                    else "expired"
                    if _as_utc(invitation.expires_at) <= _as_utc(now)
                    else "pending"
                ),
                "expires_at": invitation.expires_at.isoformat(),
                "created_at": invitation.created_at.isoformat() if invitation.created_at else None,
            }
            for invitation in invitations
        ],
    }


@router.post("/invites/accept", dependencies=[Depends(require_csrf)])
def accept_workspace_invite(
    payload: InviteAccept,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    token_hash = sha256(payload.token.encode("utf-8")).hexdigest()
    invitation = db.execute(
        select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == token_hash)
    ).scalar_one_or_none()
    now = utcnow()
    if invitation is None or not _active_invitation(invitation, now):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found or expired")
    if not principal.email or not principal.email_verified or principal.email.lower() != invitation.email.lower():
        record_audit_event(
            db,
            actor_user_id=principal.user_id,
            workspace_id=invitation.workspace_id,
            action="workspace.invite_accepted",
            target_type="invitation",
            target_id=str(invitation.id),
            outcome="denied",
            request_id=_request_id(request),
            metadata={"reason": "email_mismatch"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invitation does not match this verified identity")

    membership = db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == invitation.workspace_id,
            WorkspaceMembership.user_id == principal.user_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        db.add(
            WorkspaceMembership(
                workspace_id=invitation.workspace_id,
                user_id=principal.user_id,
                role=invitation.role,
            )
        )
    invitation.accepted_at = now
    invitation.accepted_by_user_id = principal.user_id
    record_audit_event(
        db,
        actor_user_id=principal.user_id,
        workspace_id=invitation.workspace_id,
        action="workspace.invite_accepted",
        target_type="invitation",
        target_id=str(invitation.id),
        request_id=_request_id(request),
        metadata={"role": invitation.role},
    )
    db.commit()
    return {"workspace_id": invitation.workspace_id, "role": invitation.role}


@router.delete("/workspaces/{workspace_id}/invites/{invitation_id}", dependencies=[Depends(require_csrf)])
def revoke_workspace_invite(
    workspace_id: int,
    invitation_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    access = _authorized_workspace(db, principal, workspace_id, "owner", request, "workspace.invite.revoke")
    invitation = db.execute(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == access.workspace.id,
        )
    ).scalar_one_or_none()
    if invitation is None or invitation.accepted_at or invitation.revoked_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    invitation.revoked_at = utcnow()
    invitation.revoked_by_user_id = principal.user_id
    record_audit_event(
        db,
        actor_user_id=principal.user_id,
        workspace_id=access.workspace.id,
        action="workspace.invite_revoked",
        target_type="invitation",
        target_id=str(invitation.id),
        request_id=_request_id(request),
        metadata={"email": invitation.email},
    )
    db.commit()
    return {"status": "revoked"}


@router.patch("/workspaces/{workspace_id}/members/{user_id}", dependencies=[Depends(require_csrf)])
def update_workspace_member(
    workspace_id: int,
    user_id: int,
    payload: WorkspaceMemberPatch,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    access = _authorized_workspace(db, principal, workspace_id, "owner", request, "workspace.member.update")
    membership = db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == access.workspace.id,
            WorkspaceMembership.user_id == user_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
    if membership.role == "owner":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ownership transfer is not supported")
    previous_role = membership.role
    membership.role = payload.role
    record_audit_event(
        db,
        actor_user_id=principal.user_id,
        workspace_id=access.workspace.id,
        action="workspace.member_updated",
        target_type="membership",
        target_id=str(membership.id),
        request_id=_request_id(request),
        metadata={"user_id": user_id, "previous_role": previous_role, "role": payload.role},
    )
    db.commit()
    return {"user_id": user_id, "role": membership.role}


@router.delete("/workspaces/{workspace_id}/members/{user_id}", dependencies=[Depends(require_csrf)])
def remove_workspace_member(
    workspace_id: int,
    user_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    access = _authorized_workspace(db, principal, workspace_id, "owner", request, "workspace.member.remove")
    membership = db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == access.workspace.id,
            WorkspaceMembership.user_id == user_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
    if membership.role == "owner":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The workspace owner cannot be removed")
    membership_id = membership.id
    db.delete(membership)
    record_audit_event(
        db,
        actor_user_id=principal.user_id,
        workspace_id=access.workspace.id,
        action="workspace.member_removed",
        target_type="membership",
        target_id=str(membership_id),
        request_id=_request_id(request),
        metadata={"user_id": user_id},
    )
    db.commit()
    return {"status": "removed"}


@router.get("/workspaces/{workspace_id}/audit-events")
def list_audit_events(
    workspace_id: int,
    request: Request,
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    access = _authorized_workspace(db, principal, workspace_id, "owner", request, "workspace.audit.list")
    query = (
        select(AuditEvent, User.display_name)
        .join(User, User.id == AuditEvent.actor_user_id, isouter=True)
        .where(AuditEvent.workspace_id == access.workspace.id)
        .order_by(AuditEvent.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        query = query.where(AuditEvent.id < before_id)
    rows = db.execute(query).all()
    return {
        "workspace_id": access.workspace.id,
        "items": [
            {
                "id": event.id,
                "action": event.action,
                "outcome": event.outcome,
                "target_type": event.target_type,
                "target_id": event.target_id,
                "connection_id": event.connection_id,
                "actor_name": actor_name,
                "request_id": event.request_id,
                "metadata": event.metadata_json or {},
                "created_at": event.created_at.isoformat(),
            }
            for event, actor_name in rows
        ],
        "next_before_id": rows[-1][0].id if len(rows) == limit else None,
    }
