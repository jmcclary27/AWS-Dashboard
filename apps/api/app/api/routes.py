from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Account
from app.db.session import get_db
from app.schemas.api import AccountCreate, AccountPatch, SyncResponse
from app.services.analytics import (
    build_accounts_response,
    build_forecast_response,
    build_services_response,
    build_summary_response,
    build_trends_response,
    list_anomalies_response,
    list_recommendations_response,
)
from app.services.demo_sync import run_demo_sync

router = APIRouter()


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db)) -> dict:
    return build_accounts_response(db)


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> dict:
    account = Account(**payload.model_dump())
    db.add(account)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AWS account already exists") from error

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
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(account, field, value)

    db.add(account)
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
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return run_demo_sync(db, [account.id], days=14)


@router.post("/sync/all", response_model=SyncResponse)
def sync_all_accounts(db: Session = Depends(get_db)) -> dict:
    enabled_accounts = db.scalars(select(Account.id).where(Account.enabled.is_(True))).all()
    if not enabled_accounts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No enabled accounts to sync")
    return run_demo_sync(db, list(enabled_accounts), days=14)


@router.get("/summary")
def get_summary(range: str = Query("30d"), db: Session = Depends(get_db)) -> dict:
    try:
        return build_summary_response(db, range)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/services")
def get_services(
    range: str = Query("30d"),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return build_services_response(db, range, account_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/trends")
def get_trends(
    range: str = Query("90d"),
    group_by: str = Query("account"),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return build_trends_response(db, range, group_by)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/forecast")
def get_forecast(db: Session = Depends(get_db)) -> dict:
    return build_forecast_response(db)


@router.get("/recommendations")
def get_recommendations(db: Session = Depends(get_db)) -> dict:
    return list_recommendations_response(db)


@router.get("/anomalies")
def get_anomalies(db: Session = Depends(get_db)) -> dict:
    return list_anomalies_response(db)

