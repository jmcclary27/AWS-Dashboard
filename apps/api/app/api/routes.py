from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Account, Connection, ConnectionAccount, SyncRun
from app.db.seed import ensure_connection_membership, get_demo_connection, refresh_recent_demo_data
from app.db.session import get_db
from app.schemas.api import (
    AccountCreate,
    AccountPatch,
    ConnectionCreate,
    ConnectionPatch,
    SyncRequest,
    SyncResponse,
)
from app.services.aws_access import inspect_aws_runtime, validate_connection_access
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
from app.services.connection_scope import ConnectionSelectionError, resolve_connection

router = APIRouter()


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def resolve_connection_or_400(db: Session, connection_id: int | None) -> Connection:
    try:
        return resolve_connection(db, connection_id)
    except ConnectionSelectionError as error:
        raise bad_request(str(error)) from error


def serialize_connection_item(db: Session, connection: Connection) -> dict:
    items = list_connections_response(db)["items"]
    item = next((candidate for candidate in items if candidate["id"] == connection.id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return item


def sync_response_for(connection: Connection, result) -> dict:
    return {
        "status": result.status,
        "connection_id": connection.id,
        "accounts_synced": result.accounts_synced,
        "records_written": result.records_written,
        "window_days": result.window_days,
        "message": result.message,
    }


@router.get("/connections")
def list_connections(db: Session = Depends(get_db)) -> dict:
    return list_connections_response(db)


@router.get("/aws/runtime")
def aws_runtime_status() -> dict:
    return inspect_aws_runtime()


@router.get("/connections/{connection_id}")
def get_connection(connection_id: int, db: Session = Depends(get_db)) -> dict:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return {"item": serialize_connection_item(db, connection)}


@router.post("/connections/{connection_id}/validate")
def validate_connection(connection_id: int, db: Session = Depends(get_db)) -> dict:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return validate_connection_access(db, connection)


@router.post("/connections", status_code=status.HTTP_201_CREATED)
def create_connection(payload: ConnectionCreate, db: Session = Depends(get_db)) -> dict:
    connection = Connection(
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
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connection name already exists") from error

    if payload.kind == "account_role" and payload.account:
        account = db.execute(select(Account).where(Account.aws_account_id == payload.account.aws_account_id)).scalar_one_or_none()
        if not account:
            account = Account(
                display_name=payload.account.display_name,
                aws_account_id=payload.account.aws_account_id,
                role_arn=payload.role_arn,
                external_id=payload.external_id,
                team_tag_key=payload.team_tag_key,
                enabled=True,
            )
            db.add(account)
            db.flush()
        else:
            account.display_name = payload.account.display_name
            account.role_arn = payload.role_arn
            account.external_id = payload.external_id
            account.team_tag_key = payload.team_tag_key
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

    db.commit()
    db.refresh(connection)
    return {"item": serialize_connection_item(db, connection)}


@router.patch("/connections/{connection_id}")
def update_connection(connection_id: int, payload: ConnectionPatch, db: Session = Depends(get_db)) -> dict:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    updates = payload.model_dump(exclude_unset=True)
    account_payload = updates.pop("account", None)
    for field, value in updates.items():
        setattr(connection, field, value)

    if connection.kind == "account_role":
        if not connection.role_arn:
            raise bad_request("role_arn is required for account_role connections")
        if account_payload:
            account = db.execute(select(Account).where(Account.aws_account_id == account_payload["aws_account_id"])).scalar_one_or_none()
            if not account:
                account = Account(
                    display_name=account_payload["display_name"],
                    aws_account_id=account_payload["aws_account_id"],
                    role_arn=connection.role_arn,
                    external_id=connection.external_id,
                    team_tag_key=connection.team_tag_key,
                    enabled=True,
                )
                db.add(account)
                db.flush()
            else:
                account.display_name = account_payload["display_name"]
                account.role_arn = connection.role_arn
                account.external_id = connection.external_id
                account.team_tag_key = connection.team_tag_key
                db.add(account)
                db.flush()

            memberships = db.scalars(select(ConnectionAccount).where(ConnectionAccount.connection_id == connection.id)).all()
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
    elif account_payload:
        raise bad_request("Only account_role connections accept account updates")

    db.add(connection)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connection name already exists") from error
    db.refresh(connection)
    return {"item": serialize_connection_item(db, connection)}


@router.post("/connections/{connection_id}/sync", response_model=SyncResponse)
def sync_selected_connection(
    connection_id: int,
    payload: SyncRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    try:
        result = sync_connection(db, connection, days=payload.days if payload else None)
    except CollectorExecutionError as error:
        raise bad_request(str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return sync_response_for(connection, result)


@router.get("/sync-runs")
def list_sync_runs(
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
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
                "message": run.message,
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
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
    return build_accounts_response(db, connection.id)


@router.get("/billing/overview")
def get_billing_overview(
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
    return build_billing_overview_response(db, connection.id)


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> dict:
    demo_connection = get_demo_connection(db)
    account = Account(**payload.model_dump())
    db.add(account)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AWS account already exists") from error

    ensure_connection_membership(
        db,
        connection_id=demo_connection.id,
        account_id=account.id,
        membership_source="manual",
        is_primary=False,
        enabled=account.enabled,
    )
    db.commit()
    db.refresh(account)
    return {
        "item": {
            "id": account.id,
            "display_name": account.display_name,
            "aws_account_id": account.aws_account_id,
            "enabled": account.enabled,
            "team_tag_key": account.team_tag_key,
        }
    }


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, payload: AccountPatch, db: Session = Depends(get_db)) -> dict:
    demo_connection = get_demo_connection(db)
    membership = db.execute(
        select(ConnectionAccount).where(
            ConnectionAccount.connection_id == demo_connection.id,
            ConnectionAccount.account_id == account_id,
        )
    ).scalar_one_or_none()
    if not membership:
        raise bad_request("Legacy account updates are only supported for demo-connected accounts")

    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(account, field, value)

    membership.enabled = account.enabled
    db.add(account)
    db.add(membership)
    db.commit()
    db.refresh(account)
    return {
        "item": {
            "id": account.id,
            "display_name": account.display_name,
            "aws_account_id": account.aws_account_id,
            "enabled": account.enabled,
            "team_tag_key": account.team_tag_key,
        }
    }


@router.post("/accounts/{account_id}/sync", response_model=SyncResponse)
def sync_account(account_id: int, db: Session = Depends(get_db)) -> dict:
    demo_connection = get_demo_connection(db)
    membership = db.execute(
        select(ConnectionAccount).where(
            ConnectionAccount.connection_id == demo_connection.id,
            ConnectionAccount.account_id == account_id,
        )
    ).scalar_one_or_none()
    if not membership:
        raise bad_request("Legacy per-account sync is only supported for demo-connected accounts")

    try:
        result = refresh_recent_demo_data(db, account_ids=[account_id], days=14, connection_id=demo_connection.id)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return {
        "status": "success",
        "connection_id": demo_connection.id,
        "accounts_synced": result["accounts_synced"],
        "records_written": result["records_written"],
        "window_days": 14,
        "message": None,
    }


@router.post("/sync/all", response_model=SyncResponse)
def sync_all_accounts(db: Session = Depends(get_db)) -> dict:
    demo_connection = get_demo_connection(db)
    try:
        result = sync_connection(db, demo_connection, days=14)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return sync_response_for(demo_connection, result)


@router.get("/summary")
def get_summary(
    range: str = Query("30d"),
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
    try:
        return build_summary_response(db, connection.id, range)
    except ValueError as error:
        raise bad_request(str(error)) from error


@router.get("/services")
def get_services(
    range: str = Query("30d"),
    account_id: int | None = Query(default=None),
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
    try:
        return build_services_response(db, connection.id, range, account_id)
    except ValueError as error:
        raise bad_request(str(error)) from error


@router.get("/trends")
def get_trends(
    range: str = Query("90d"),
    group_by: str = Query("account"),
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
    try:
        return build_trends_response(db, connection.id, range, group_by)
    except ValueError as error:
        raise bad_request(str(error)) from error


@router.get("/forecast")
def get_forecast(
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
    return build_forecast_response(db, connection.id)


@router.get("/recommendations")
def get_recommendations(
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
    return list_recommendations_response(db, connection.id)


@router.get("/anomalies")
def get_anomalies(
    connection_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    connection = resolve_connection_or_400(db, connection_id)
    return list_anomalies_response(db, connection.id)
