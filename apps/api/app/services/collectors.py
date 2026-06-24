from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Connection,
    ConnectionAccount,
    DailyAccountCost,
    DailyServiceCost,
    DailyTeamCost,
    Forecast,
    SyncRun,
)
from app.db.seed import (
    clear_connection_window_data,
    get_connection_accounts,
    get_unallocated_team_id,
    rebuild_connection_anomalies,
    rebuild_connection_recommendations,
    rebuild_local_forecasts,
    refresh_recent_demo_data,
    resolve_team_id_for_tag_value,
)


class CollectorExecutionError(RuntimeError):
    pass


@dataclass
class CollectorResult:
    status: str
    accounts_synced: int
    records_written: int
    window_days: int
    message: str | None = None


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def get_boto3_session():
    try:
        import boto3
    except ImportError as error:
        raise CollectorExecutionError("boto3 is required for AWS-backed collectors") from error
    return boto3.session.Session()


def assume_role_session(role_arn: str, external_id: str | None):
    session = get_boto3_session()
    sts = session.client("sts")
    params: dict[str, Any] = {
        "RoleArn": role_arn,
        "RoleSessionName": "aws-dashboard-sync",
    }
    if external_id:
        params["ExternalId"] = external_id
    credentials = sts.assume_role(**params)["Credentials"]
    return session.__class__(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )


def build_cost_explorer_client(connection: Connection):
    if connection.kind == "org_management":
        session = assume_role_session(connection.role_arn, connection.external_id) if connection.role_arn else get_boto3_session()
    elif connection.kind == "account_role":
        if not connection.role_arn:
            raise CollectorExecutionError("Standalone account-role connections require role_arn")
        session = assume_role_session(connection.role_arn, connection.external_id)
    else:
        raise CollectorExecutionError(f"Unsupported collector kind '{connection.kind}'")

    return session.client("ce", region_name="us-east-1")


def build_ce_request(
    connection: Connection,
    start_day: date,
    end_day_exclusive: date,
    group_by: list[dict[str, str]] | None = None,
    metric: str = "UnblendedCost",
    filter_expression: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "TimePeriod": {"Start": start_day.isoformat(), "End": end_day_exclusive.isoformat()},
        "Granularity": "DAILY",
        "Metrics": [metric],
    }
    if group_by:
        request["GroupBy"] = group_by
    if filter_expression:
        request["Filter"] = filter_expression
    if connection.billing_view_arn:
        request["BillingViewArn"] = connection.billing_view_arn
    return request


def paginate_cost_and_usage(client: Any, request: dict[str, Any]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    next_token: str | None = None
    while True:
        response = client.get_cost_and_usage(**({**request, "NextPageToken": next_token} if next_token else request))
        pages.append(response)
        next_token = response.get("NextPageToken")
        if not next_token:
            return pages


def extract_dimension_names(pages: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for page in pages:
        for item in page.get("DimensionValueAttributes", []):
            value = item.get("Value")
            if not value:
                continue
            attributes = item.get("Attributes", {})
            display_name = next((attr_value for attr_value in attributes.values() if attr_value), value)
            names[value] = display_name
    return names


def metric_amount(group: dict[str, Any]) -> float:
    return round(float(group["Metrics"]["UnblendedCost"]["Amount"]), 2)


def upsert_canonical_account(session: Session, aws_account_id: str, display_name: str, team_tag_key: str) -> Account:
    account = session.execute(select(Account).where(Account.aws_account_id == aws_account_id)).scalar_one_or_none()
    if not account:
        account = Account(
            display_name=display_name,
            aws_account_id=aws_account_id,
            team_tag_key=team_tag_key,
            enabled=True,
        )
        session.add(account)
        session.flush()
        return account

    if display_name and (not account.display_name or account.display_name == account.aws_account_id):
        account.display_name = display_name
    if not account.team_tag_key:
        account.team_tag_key = team_tag_key
    session.add(account)
    session.flush()
    return account


def ensure_membership(
    session: Session,
    connection: Connection,
    account: Account,
    membership_source: str,
    is_primary: bool = False,
) -> ConnectionAccount:
    membership = session.execute(
        select(ConnectionAccount).where(
            ConnectionAccount.connection_id == connection.id,
            ConnectionAccount.account_id == account.id,
        )
    ).scalar_one_or_none()
    if membership:
        membership.membership_source = membership_source
        membership.enabled = True
        membership.is_primary = is_primary
        session.add(membership)
        session.flush()
        return membership

    membership = ConnectionAccount(
        connection_id=connection.id,
        account_id=account.id,
        membership_source=membership_source,
        enabled=True,
        is_primary=is_primary,
    )
    session.add(membership)
    session.flush()
    return membership


def get_primary_membership(session: Session, connection_id: int) -> ConnectionAccount:
    membership = session.execute(
        select(ConnectionAccount).where(
            ConnectionAccount.connection_id == connection_id,
            ConnectionAccount.is_primary.is_(True),
            ConnectionAccount.enabled.is_(True),
        )
    ).scalar_one_or_none()
    if not membership:
        raise CollectorExecutionError("Standalone account-role connections require one primary account membership")
    return membership


def write_connection_window(
    session: Session,
    connection_id: int,
    start_day: date,
    end_day: date,
    account_totals: dict[tuple[int, date], float],
    service_rows: dict[tuple[int, date, str], float],
    team_rows: dict[tuple[int, date, int], float],
) -> int:
    account_ids = sorted({account_id for account_id, _ in account_totals})
    clear_connection_window_data(session, connection_id, account_ids, start_day, end_day)

    records_written = 0
    for (account_id, current_day), amount in sorted(account_totals.items(), key=lambda item: (item[0][0], item[0][1])):
        session.add(
            DailyAccountCost(
                connection_id=connection_id,
                account_id=account_id,
                day=current_day,
                cost_usd=round(amount, 2),
            )
        )
        records_written += 1

    for (account_id, current_day, service_name), amount in sorted(service_rows.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
        session.add(
            DailyServiceCost(
                connection_id=connection_id,
                account_id=account_id,
                day=current_day,
                service_name=service_name,
                cost_usd=round(amount, 2),
            )
        )
        records_written += 1

    for (account_id, current_day, team_id), amount in sorted(team_rows.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
        session.add(
            DailyTeamCost(
                connection_id=connection_id,
                account_id=account_id,
                day=current_day,
                team_id=team_id,
                cost_usd=round(amount, 2),
            )
        )
        records_written += 1

    session.flush()
    return records_written


def write_aws_forecasts(
    session: Session,
    client: Any,
    connection: Connection,
    account_ids_by_aws_id: dict[str, int],
    as_of: date,
) -> int:
    session.execute(delete(Forecast).where(Forecast.connection_id == connection.id))
    month_start = as_of.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    def forecast_request(filter_expression: dict[str, Any] | None = None) -> dict[str, Any]:
        request: dict[str, Any] = {
            "TimePeriod": {"Start": as_of.isoformat(), "End": next_month.isoformat()},
            "Granularity": "DAILY",
            "Metric": "UNBLENDED_COST",
        }
        if filter_expression:
            request["Filter"] = filter_expression
        if connection.billing_view_arn:
            request["BillingViewArn"] = connection.billing_view_arn
        return request

    records_written = 0
    overall = client.get_cost_forecast(**forecast_request())
    for point in overall.get("ForecastResultsByTime", []):
        forecast_day = date.fromisoformat(point["TimePeriod"]["Start"])
        if forecast_day <= as_of:
            continue
        session.add(
            Forecast(
                connection_id=connection.id,
                account_id=None,
                day=forecast_day,
                projected_cost_usd=round(float(point["MeanValue"]), 2),
                model_version="aws-ce-v1",
            )
        )
        records_written += 1

    for aws_account_id, account_id in account_ids_by_aws_id.items():
        account_forecast = client.get_cost_forecast(
            **forecast_request(
                {
                    "Dimensions": {
                        "Key": "LINKED_ACCOUNT",
                        "Values": [aws_account_id],
                    }
                }
            )
        )
        for point in account_forecast.get("ForecastResultsByTime", []):
            forecast_day = date.fromisoformat(point["TimePeriod"]["Start"])
            if forecast_day <= as_of:
                continue
            session.add(
                Forecast(
                    connection_id=connection.id,
                    account_id=account_id,
                    day=forecast_day,
                    projected_cost_usd=round(float(point["MeanValue"]), 2),
                    model_version="aws-ce-v1",
                )
            )
            records_written += 1

    session.flush()
    return records_written


def write_account_role_forecasts(session: Session, client: Any, connection: Connection, account_id: int, as_of: date) -> int:
    session.execute(delete(Forecast).where(Forecast.connection_id == connection.id))
    month_start = as_of.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    request: dict[str, Any] = {
        "TimePeriod": {"Start": as_of.isoformat(), "End": next_month.isoformat()},
        "Granularity": "DAILY",
        "Metric": "UNBLENDED_COST",
    }
    if connection.billing_view_arn:
        request["BillingViewArn"] = connection.billing_view_arn

    response = client.get_cost_forecast(**request)
    records_written = 0
    for point in response.get("ForecastResultsByTime", []):
        forecast_day = date.fromisoformat(point["TimePeriod"]["Start"])
        if forecast_day <= as_of:
            continue
        amount = round(float(point["MeanValue"]), 2)
        session.add(
            Forecast(
                connection_id=connection.id,
                account_id=None,
                day=forecast_day,
                projected_cost_usd=amount,
                model_version="aws-ce-v1",
            )
        )
        session.add(
            Forecast(
                connection_id=connection.id,
                account_id=account_id,
                day=forecast_day,
                projected_cost_usd=amount,
                model_version="aws-ce-v1",
            )
        )
        records_written += 2

    session.flush()
    return records_written


def build_unallocated_team_rows(session: Session, account_totals: dict[tuple[int, date], float]) -> dict[tuple[int, date, int], float]:
    unallocated_team_id = get_unallocated_team_id(session)
    team_rows: dict[tuple[int, date, int], float] = {}
    for (account_id, current_day), amount in account_totals.items():
        team_rows[(account_id, current_day, unallocated_team_id)] = round(amount, 2)
    return team_rows


def collect_org_management(session: Session, connection: Connection, days: int) -> CollectorResult:
    client = build_cost_explorer_client(connection)
    end_day = utc_today()
    start_day = end_day - timedelta(days=max(days - 1, 0))
    end_day_exclusive = end_day + timedelta(days=1)

    service_pages = paginate_cost_and_usage(
        client,
        build_ce_request(
            connection,
            start_day,
            end_day_exclusive,
            group_by=[
                {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
                {"Type": "DIMENSION", "Key": "SERVICE"},
            ],
        ),
    )
    account_names = extract_dimension_names(service_pages)
    raw_service_rows: list[tuple[str, date, str, float]] = []
    for page in service_pages:
        for bucket in page.get("ResultsByTime", []):
            current_day = date.fromisoformat(bucket["TimePeriod"]["Start"])
            for group in bucket.get("Groups", []):
                linked_account_id, service_name = group["Keys"]
                raw_service_rows.append((linked_account_id, current_day, service_name, metric_amount(group)))

    account_ids_by_aws_id: dict[str, int] = {}
    for linked_account_id in sorted({row[0] for row in raw_service_rows}):
        account = upsert_canonical_account(
            session,
            linked_account_id,
            account_names.get(linked_account_id, linked_account_id),
            connection.team_tag_key,
        )
        ensure_membership(session, connection, account, membership_source="discovered")
        account_ids_by_aws_id[linked_account_id] = account.id

    service_rows: dict[tuple[int, date, str], float] = defaultdict(float)
    account_totals: dict[tuple[int, date], float] = defaultdict(float)
    for linked_account_id, current_day, service_name, amount in raw_service_rows:
        account_id = account_ids_by_aws_id[linked_account_id]
        service_rows[(account_id, current_day, service_name)] += amount
        account_totals[(account_id, current_day)] += amount

    tag_query_failed = False
    tag_error_message = None
    team_rows: dict[tuple[int, date, int], float] = defaultdict(float)
    try:
        tag_pages = paginate_cost_and_usage(
            client,
            build_ce_request(
                connection,
                start_day,
                end_day_exclusive,
                group_by=[
                    {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
                    {"Type": "TAG", "Key": connection.team_tag_key},
                ],
            ),
        )
        for page in tag_pages:
            for bucket in page.get("ResultsByTime", []):
                current_day = date.fromisoformat(bucket["TimePeriod"]["Start"])
                for group in bucket.get("Groups", []):
                    linked_account_id, tag_value = group["Keys"]
                    account_id = account_ids_by_aws_id.get(linked_account_id)
                    if not account_id:
                        continue
                    team_id = resolve_team_id_for_tag_value(session, tag_value)
                    team_rows[(account_id, current_day, team_id)] += metric_amount(group)
    except Exception as error:
        tag_query_failed = True
        tag_error_message = str(error)
        team_rows = defaultdict(float, build_unallocated_team_rows(session, account_totals))

    records_written = write_connection_window(
        session,
        connection.id,
        start_day,
        end_day,
        dict(account_totals),
        dict(service_rows),
        dict(team_rows),
    )

    try:
        records_written += write_aws_forecasts(session, client, connection, account_ids_by_aws_id, end_day)
    except Exception:
        rebuild_local_forecasts(session, connection.id, end_day, model_version="aws-local-fallback-v1")

    rebuild_connection_anomalies(session, connection.id, end_day)
    rebuild_connection_recommendations(session, connection.id, end_day)

    message = tag_error_message if tag_query_failed else None
    return CollectorResult(
        status="partial_success" if tag_query_failed else "success",
        accounts_synced=len(account_ids_by_aws_id),
        records_written=records_written,
        window_days=days,
        message=message,
    )


def collect_account_role(session: Session, connection: Connection, days: int) -> CollectorResult:
    membership = get_primary_membership(session, connection.id)
    account = session.get(Account, membership.account_id)
    if not account:
        raise CollectorExecutionError("Primary connection account not found")

    client = build_cost_explorer_client(connection)
    end_day = utc_today()
    start_day = end_day - timedelta(days=max(days - 1, 0))
    end_day_exclusive = end_day + timedelta(days=1)

    service_pages = paginate_cost_and_usage(
        client,
        build_ce_request(
            connection,
            start_day,
            end_day_exclusive,
            group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        ),
    )

    service_rows: dict[tuple[int, date, str], float] = defaultdict(float)
    account_totals: dict[tuple[int, date], float] = defaultdict(float)
    for page in service_pages:
        for bucket in page.get("ResultsByTime", []):
            current_day = date.fromisoformat(bucket["TimePeriod"]["Start"])
            for group in bucket.get("Groups", []):
                service_name = group["Keys"][0]
                amount = metric_amount(group)
                service_rows[(account.id, current_day, service_name)] += amount
                account_totals[(account.id, current_day)] += amount

    tag_query_failed = False
    tag_error_message = None
    team_rows: dict[tuple[int, date, int], float] = defaultdict(float)
    try:
        tag_pages = paginate_cost_and_usage(
            client,
            build_ce_request(
                connection,
                start_day,
                end_day_exclusive,
                group_by=[{"Type": "TAG", "Key": connection.team_tag_key}],
            ),
        )
        for page in tag_pages:
            for bucket in page.get("ResultsByTime", []):
                current_day = date.fromisoformat(bucket["TimePeriod"]["Start"])
                for group in bucket.get("Groups", []):
                    tag_value = group["Keys"][0]
                    team_id = resolve_team_id_for_tag_value(session, tag_value)
                    team_rows[(account.id, current_day, team_id)] += metric_amount(group)
    except Exception as error:
        tag_query_failed = True
        tag_error_message = str(error)
        team_rows = defaultdict(float, build_unallocated_team_rows(session, account_totals))

    records_written = write_connection_window(
        session,
        connection.id,
        start_day,
        end_day,
        dict(account_totals),
        dict(service_rows),
        dict(team_rows),
    )

    try:
        records_written += write_account_role_forecasts(session, client, connection, account.id, end_day)
    except Exception:
        rebuild_local_forecasts(session, connection.id, end_day, model_version="aws-local-fallback-v1")

    rebuild_connection_anomalies(session, connection.id, end_day)
    rebuild_connection_recommendations(session, connection.id, end_day)

    message = tag_error_message if tag_query_failed else None
    return CollectorResult(
        status="partial_success" if tag_query_failed else "success",
        accounts_synced=1,
        records_written=records_written,
        window_days=days,
        message=message,
    )


def record_sync_run(
    session: Session,
    connection: Connection,
    status: str,
    days: int,
    records_written: int,
    accounts_synced: int,
    message: str | None,
    account_id: int | None = None,
) -> None:
    timestamp = datetime.now(timezone.utc)
    session.add(
        SyncRun(
            connection_id=connection.id,
            account_id=account_id,
            sync_type=connection.kind,
            status=status,
            message=message,
            window_days=days,
            accounts_synced=accounts_synced,
            started_at=timestamp,
            finished_at=timestamp,
            records_written=records_written,
        )
    )


def sync_connection(session: Session, connection: Connection, days: int = 14) -> CollectorResult:
    try:
        if connection.kind == "demo":
            result_data = refresh_recent_demo_data(session, days=days, connection_id=connection.id)
            return CollectorResult(
                status="success",
                accounts_synced=result_data["accounts_synced"],
                records_written=result_data["records_written"],
                window_days=days,
            )
        if connection.kind == "org_management":
            result = collect_org_management(session, connection, days)
        elif connection.kind == "account_role":
            result = collect_account_role(session, connection, days)
        else:
            raise CollectorExecutionError(f"Unsupported connection kind '{connection.kind}'")

        record_sync_run(
            session,
            connection,
            status=result.status,
            days=result.window_days,
            records_written=result.records_written,
            accounts_synced=result.accounts_synced,
            message=result.message,
        )
        session.commit()
        return result
    except Exception as error:
        session.rollback()
        if connection.kind != "demo":
            record_sync_run(
                session,
                connection,
                status="failed",
                days=days,
                records_written=0,
                accounts_synced=0,
                message=str(error),
            )
            session.commit()
        raise
