from __future__ import annotations

import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from importlib import import_module
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Account, BillingForecast, Connection, ConnectionAccount, DailyAccountCost, DailyBillingTotal
from app.services.aws_access import build_aws_session_for_connection, describe_aws_error

BILLING_MODE_USAGE_ONLY = "usage_only"
BILLING_MODE_PAYABLE_HYBRID = "payable_hybrid"

TRUTH_MODE_EXACT = "exact"
TRUTH_MODE_APPROXIMATE = "approximate"

SOURCE_KIND_DATA_EXPORT = "data_export"
SOURCE_KIND_CE_NET_FALLBACK = "ce_net_fallback"
SOURCE_KIND_DEMO = "demo"

EXPORT_FRESHNESS_HOURS = 72
METRIC_NET_UNBLENDED_COST = "NetUnblendedCost"

USAGE_LIKE_LINE_TYPES = {"Usage", "DiscountedUsage", "SavingsPlanCoveredUsage"}
COMMITMENT_FEE_LINE_TYPES = {"Fee", "RIFee", "SavingsPlanRecurringFee", "SavingsPlanUpfrontFee"}
OFFSET_LINE_TYPES = {
    "BundledDiscount",
    "Discount",
    "EdpDiscount",
    "PrivateRateDiscount",
    "SavingsPlanNegation",
}

CUR_FIELD_ALIASES = {
    "usage_account_id": ("line_item_usage_account_id", "lineItem/UsageAccountId"),
    "line_item_type": ("line_item_line_item_type", "lineItem/LineItemType"),
    "product_code": ("line_item_product_code", "lineItem/ProductCode", "product_product_name", "product/ProductName"),
    "billing_entity": ("bill_billing_entity", "bill/BillingEntity"),
    "usage_start": ("line_item_usage_start_date", "lineItem/UsageStartDate"),
    "bill_period_start": ("bill_billing_period_start_date", "bill/BillingPeriodStartDate"),
    "unblended_cost": ("line_item_unblended_cost", "lineItem/UnblendedCost"),
    "net_unblended_cost": ("line_item_net_unblended_cost", "lineItem/NetUnblendedCost"),
}


@dataclass
class BillingSyncResult:
    truth_mode: str
    records_written: int
    message: str | None = None


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def first_day_of_month(value: date) -> date:
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    year = value.year + ((value.month - 1 + months) // 12)
    month = ((value.month - 1 + months) % 12) + 1
    return date(year, month, 1)


def next_month_start(value: date) -> date:
    return add_months(first_day_of_month(value), 1)


def days_in_month(value: date) -> int:
    return (next_month_start(value) - first_day_of_month(value)).days


def iter_days(start_day: date, end_day: date) -> list[date]:
    days: list[date] = []
    cursor = start_day
    while cursor <= end_day:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def history_window_start(as_of: date) -> date:
    return add_months(first_day_of_month(as_of), -3)


def billing_export_configured(connection: Connection) -> bool:
    return bool(connection.billing_export_bucket and connection.billing_export_prefix and connection.billing_export_region)


def connection_truth_mode(connection: Connection, has_exact_rows: bool = False) -> str:
    if connection.kind == "demo":
        return TRUTH_MODE_EXACT
    if connection.billing_mode != BILLING_MODE_PAYABLE_HYBRID:
        return TRUTH_MODE_APPROXIMATE
    return TRUTH_MODE_EXACT if has_exact_rows else TRUTH_MODE_APPROXIMATE


def pick_field(row: dict[str, Any], alias_key: str) -> Any:
    for field_name in CUR_FIELD_ALIASES[alias_key]:
        if field_name in row and row[field_name] not in (None, ""):
            return row[field_name]
    return None


def parse_money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_day(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def round_money(value: float) -> float:
    return round(float(value), 2)


def blank_billing_totals(source_kind: str) -> dict[str, float | str]:
    return {
        "gross_usage_usd": 0.0,
        "credits_usd": 0.0,
        "savings_discounts_usd": 0.0,
        "tax_usd": 0.0,
        "support_usd": 0.0,
        "marketplace_usd": 0.0,
        "refunds_usd": 0.0,
        "other_adjustments_usd": 0.0,
        "net_due_usd": 0.0,
        "source_kind": source_kind,
    }


def normalize_line_item_type(value: Any) -> str:
    if value in (None, ""):
        return "Usage"
    return str(value).strip()


def is_support_charge(product_code: str, billing_entity: str) -> bool:
    lower = f"{product_code} {billing_entity}".lower()
    return "support" in lower


def is_marketplace_charge(product_code: str, billing_entity: str) -> bool:
    lower = f"{product_code} {billing_entity}".lower()
    return "marketplace" in lower


def coalesce_cost(net_cost: float | None, unblended_cost: float | None) -> tuple[float, float]:
    gross = float(unblended_cost or 0.0)
    net = float(net_cost if net_cost is not None else gross)
    return gross, net


def append_usage_only_bucket(bucket: dict[str, float | str], amount: float, source_kind: str) -> None:
    bucket["source_kind"] = source_kind
    bucket["gross_usage_usd"] = float(bucket["gross_usage_usd"]) + max(amount, 0.0)
    bucket["net_due_usd"] = float(bucket["net_due_usd"]) + amount


def aggregate_data_export_rows(
    rows: list[dict[str, Any]],
    account_ids_by_aws_id: dict[str, int],
    start_day: date,
    end_day: date,
) -> dict[tuple[int | None, date], dict[str, float | str]]:
    aggregates: dict[tuple[int | None, date], dict[str, float | str]] = {}

    for row in rows:
        raw_day = pick_field(row, "usage_start") or pick_field(row, "bill_period_start")
        current_day = parse_day(raw_day)
        if not current_day or current_day < start_day or current_day > end_day:
            continue

        raw_account_id = pick_field(row, "usage_account_id")
        aws_account_id = str(raw_account_id).strip() if raw_account_id not in (None, "") else ""
        account_id = account_ids_by_aws_id.get(aws_account_id) if aws_account_id else None
        line_item_type = normalize_line_item_type(pick_field(row, "line_item_type"))
        product_code = str(pick_field(row, "product_code") or "").strip()
        billing_entity = str(pick_field(row, "billing_entity") or "").strip()

        gross_cost, net_cost = coalesce_cost(
            parse_money(pick_field(row, "net_unblended_cost")),
            parse_money(pick_field(row, "unblended_cost")),
        )

        bucket = aggregates.setdefault((account_id, current_day), blank_billing_totals(SOURCE_KIND_DATA_EXPORT))
        bucket["source_kind"] = SOURCE_KIND_DATA_EXPORT
        bucket["net_due_usd"] = float(bucket["net_due_usd"]) + net_cost

        if line_item_type == "Credit":
            bucket["credits_usd"] = float(bucket["credits_usd"]) + abs(net_cost or gross_cost)
            continue
        if line_item_type == "Refund":
            bucket["refunds_usd"] = float(bucket["refunds_usd"]) + abs(net_cost or gross_cost)
            continue
        if line_item_type == "Tax":
            bucket["tax_usd"] = float(bucket["tax_usd"]) + max(net_cost, 0.0)
            continue
        if is_marketplace_charge(product_code, billing_entity):
            bucket["marketplace_usd"] = float(bucket["marketplace_usd"]) + net_cost
            continue
        if is_support_charge(product_code, billing_entity):
            bucket["support_usd"] = float(bucket["support_usd"]) + net_cost
            continue
        if line_item_type in OFFSET_LINE_TYPES or (gross_cost <= 0.0 and net_cost < 0.0):
            bucket["savings_discounts_usd"] = float(bucket["savings_discounts_usd"]) + abs(net_cost or gross_cost)
            continue
        if line_item_type in COMMITMENT_FEE_LINE_TYPES:
            bucket["other_adjustments_usd"] = float(bucket["other_adjustments_usd"]) + net_cost
            continue

        if line_item_type in USAGE_LIKE_LINE_TYPES or gross_cost > 0.0:
            bucket["gross_usage_usd"] = float(bucket["gross_usage_usd"]) + max(gross_cost, 0.0)
            if gross_cost > max(net_cost, 0.0):
                bucket["savings_discounts_usd"] = float(bucket["savings_discounts_usd"]) + (gross_cost - max(net_cost, 0.0))
            elif net_cost < 0.0:
                bucket["savings_discounts_usd"] = float(bucket["savings_discounts_usd"]) + abs(net_cost)
            continue

        bucket["other_adjustments_usd"] = float(bucket["other_adjustments_usd"]) + net_cost

    return aggregates


def list_parquet_objects(s3_client: Any, bucket: str, prefix: str) -> tuple[list[dict[str, Any]], datetime | None]:
    paginator = s3_client.get_paginator("list_objects_v2")
    objects: list[dict[str, Any]] = []
    latest_modified: datetime | None = None

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if not key.endswith(".parquet"):
                continue
            objects.append(item)
            modified = item.get("LastModified")
            if modified and (latest_modified is None or modified > latest_modified):
                latest_modified = modified

    return objects, latest_modified


def parquet_rows_from_s3_object(s3_client: Any, bucket: str, key: str) -> list[dict[str, Any]]:
    try:
        parquet = import_module("pyarrow.parquet")
    except ModuleNotFoundError as error:
        raise RuntimeError("pyarrow is required to read AWS Data Exports parquet files") from error

    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    table = parquet.read_table(io.BytesIO(body))
    rows: list[dict[str, Any]] = []
    for batch in table.to_batches():
        column_names = list(batch.schema.names)
        columns = [batch.column(index).to_pylist() for index in range(batch.num_columns)]
        for values in zip(*columns):
            rows.append(dict(zip(column_names, values)))
    return rows


def load_data_export_aggregates(
    s3_client: Any,
    bucket: str,
    prefix: str,
    account_ids_by_aws_id: dict[str, int],
    start_day: date,
    end_day: date,
) -> tuple[dict[tuple[int | None, date], dict[str, float | str]], datetime | None]:
    objects, latest_modified = list_parquet_objects(s3_client, bucket, prefix)
    if not objects:
        return {}, latest_modified

    rows: list[dict[str, Any]] = []
    for item in objects:
        rows.extend(parquet_rows_from_s3_object(s3_client, bucket, item["Key"]))
    return aggregate_data_export_rows(rows, account_ids_by_aws_id, start_day, end_day), latest_modified


def latest_export_is_fresh(latest_modified: datetime | None, now: datetime | None = None) -> bool:
    if latest_modified is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - latest_modified.astimezone(timezone.utc)) <= timedelta(hours=EXPORT_FRESHNESS_HOURS)


def write_daily_billing_totals(
    session: Session,
    connection_id: int,
    aggregates: dict[tuple[int | None, date], dict[str, float | str]],
) -> int:
    records_written = 0
    for (account_id, current_day), values in sorted(
        aggregates.items(),
        key=lambda item: (item[0][1], item[0][0] is not None, item[0][0] or 0),
    ):
        session.add(
            DailyBillingTotal(
                connection_id=connection_id,
                account_id=account_id,
                day=current_day,
                gross_usage_usd=round_money(float(values["gross_usage_usd"])),
                credits_usd=round_money(float(values["credits_usd"])),
                savings_discounts_usd=round_money(float(values["savings_discounts_usd"])),
                tax_usd=round_money(float(values["tax_usd"])),
                support_usd=round_money(float(values["support_usd"])),
                marketplace_usd=round_money(float(values["marketplace_usd"])),
                refunds_usd=round_money(float(values["refunds_usd"])),
                other_adjustments_usd=round_money(float(values["other_adjustments_usd"])),
                net_due_usd=round_money(float(values["net_due_usd"])),
                source_kind=str(values["source_kind"]),
            )
        )
        records_written += 1
    session.flush()
    return records_written


def build_ce_request(
    connection: Connection,
    start_day: date,
    end_day_exclusive: date,
    metric: str,
    group_by: list[dict[str, str]] | None = None,
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


def metric_amount(container: dict[str, Any], metric: str) -> float:
    metrics = container.get("Metrics") or container.get("Total") or {}
    return round(float(metrics.get(metric, {}).get("Amount", 0.0)), 2)


def build_ce_net_fallback_actuals(
    connection: Connection,
    account_ids_by_aws_id: dict[str, int],
    as_of: date,
    client: Any | None = None,
) -> dict[tuple[int | None, date], dict[str, float | str]]:
    if client is None:
        aws_session = build_aws_session_for_connection(connection)
        client = aws_session.client("ce", region_name="us-east-1")
    start_day = history_window_start(as_of)
    end_day_exclusive = as_of + timedelta(days=1)

    aggregates: dict[tuple[int | None, date], dict[str, float | str]] = {}
    daily_overall: dict[date, float] = defaultdict(float)
    daily_account_sum: dict[date, float] = defaultdict(float)

    if connection.kind == "org_management":
        try:
            overall_pages = paginate_cost_and_usage(
                client,
                build_ce_request(connection, start_day, end_day_exclusive, metric=METRIC_NET_UNBLENDED_COST),
            )
            for page in overall_pages:
                for bucket in page.get("ResultsByTime", []):
                    current_day = date.fromisoformat(bucket["TimePeriod"]["Start"])
                    daily_overall[current_day] += metric_amount({"Total": bucket.get("Total", {})}, METRIC_NET_UNBLENDED_COST)
        except Exception:
            overall_pages = []

        try:
            account_pages = paginate_cost_and_usage(
                client,
                build_ce_request(
                    connection,
                    start_day,
                    end_day_exclusive,
                    metric=METRIC_NET_UNBLENDED_COST,
                    group_by=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}],
                ),
            )
            for page in account_pages:
                for bucket in page.get("ResultsByTime", []):
                    current_day = date.fromisoformat(bucket["TimePeriod"]["Start"])
                    for group in bucket.get("Groups", []):
                        aws_account_id = group["Keys"][0]
                        account_id = account_ids_by_aws_id.get(aws_account_id)
                        if account_id is None:
                            continue
                        amount = metric_amount(group, METRIC_NET_UNBLENDED_COST)
                        daily_account_sum[current_day] += amount
                        target = aggregates.setdefault((account_id, current_day), blank_billing_totals(SOURCE_KIND_CE_NET_FALLBACK))
                        append_usage_only_bucket(target, amount, SOURCE_KIND_CE_NET_FALLBACK)
        except Exception:
            service_pages = paginate_cost_and_usage(
                client,
                build_ce_request(
                    connection,
                    start_day,
                    end_day_exclusive,
                    metric=METRIC_NET_UNBLENDED_COST,
                    group_by=[
                        {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
                        {"Type": "DIMENSION", "Key": "SERVICE"},
                    ],
                ),
            )
            for page in service_pages:
                for bucket in page.get("ResultsByTime", []):
                    current_day = date.fromisoformat(bucket["TimePeriod"]["Start"])
                    for group in bucket.get("Groups", []):
                        aws_account_id = group["Keys"][0]
                        account_id = account_ids_by_aws_id.get(aws_account_id)
                        if account_id is None:
                            continue
                        amount = metric_amount(group, METRIC_NET_UNBLENDED_COST)
                        daily_account_sum[current_day] += amount
                        target = aggregates.setdefault((account_id, current_day), blank_billing_totals(SOURCE_KIND_CE_NET_FALLBACK))
                        append_usage_only_bucket(target, amount, SOURCE_KIND_CE_NET_FALLBACK)
        if not daily_overall:
            daily_overall.update(daily_account_sum)
    else:
        primary_account_id = next(iter(account_ids_by_aws_id.values()), None)
        if primary_account_id is not None:
            service_pages = paginate_cost_and_usage(
                client,
                build_ce_request(
                    connection,
                    start_day,
                    end_day_exclusive,
                    metric=METRIC_NET_UNBLENDED_COST,
                    group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
                ),
            )
            for page in service_pages:
                for bucket in page.get("ResultsByTime", []):
                    current_day = date.fromisoformat(bucket["TimePeriod"]["Start"])
                    total_amount = sum(metric_amount(group, METRIC_NET_UNBLENDED_COST) for group in bucket.get("Groups", []))
                    target = aggregates.setdefault((primary_account_id, current_day), blank_billing_totals(SOURCE_KIND_CE_NET_FALLBACK))
                    append_usage_only_bucket(target, total_amount, SOURCE_KIND_CE_NET_FALLBACK)

    if connection.kind == "org_management":
        for current_day, total_amount in daily_overall.items():
            shared_amount = round_money(total_amount - daily_account_sum.get(current_day, 0.0))
            if abs(shared_amount) < 0.01:
                continue
            target = aggregates.setdefault((None, current_day), blank_billing_totals(SOURCE_KIND_CE_NET_FALLBACK))
            append_usage_only_bucket(target, shared_amount, SOURCE_KIND_CE_NET_FALLBACK)

    return aggregates


def write_billing_forecasts(
    session: Session,
    connection: Connection,
    account_ids_by_aws_id: dict[str, int],
    as_of: date,
    truth_mode: str,
    client: Any | None = None,
) -> int:
    session.execute(delete(BillingForecast).where(BillingForecast.connection_id == connection.id))
    month_end = next_month_start(as_of) - timedelta(days=1)
    if as_of >= month_end:
        session.flush()
        return 0

    if client is None:
        aws_session = build_aws_session_for_connection(connection)
        client = aws_session.client("ce", region_name="us-east-1")
    forecast_request: dict[str, Any] = {
        "TimePeriod": {"Start": as_of.isoformat(), "End": next_month_start(as_of).isoformat()},
        "Granularity": "DAILY",
        "Metric": "NET_UNBLENDED_COST",
    }
    if connection.billing_view_arn:
        forecast_request["BillingViewArn"] = connection.billing_view_arn

    records_written = 0
    overall_projection: dict[date, float] = defaultdict(float)

    try:
        overall_response = client.get_cost_forecast(**forecast_request)
        for point in overall_response.get("ForecastResultsByTime", []):
            forecast_day = date.fromisoformat(point["TimePeriod"]["Start"])
            if forecast_day <= as_of:
                continue
            overall_projection[forecast_day] += round(float(point["MeanValue"]), 2)

        for aws_account_id, account_id in sorted(account_ids_by_aws_id.items()):
            account_request = dict(forecast_request)
            if connection.kind == "org_management":
                account_request["Filter"] = {
                    "Dimensions": {
                        "Key": "LINKED_ACCOUNT",
                        "Values": [aws_account_id],
                    }
                }
            account_response = client.get_cost_forecast(**account_request)
            for point in account_response.get("ForecastResultsByTime", []):
                forecast_day = date.fromisoformat(point["TimePeriod"]["Start"])
                if forecast_day <= as_of:
                    continue
                amount = round(float(point["MeanValue"]), 2)
                session.add(
                    BillingForecast(
                        connection_id=connection.id,
                        account_id=account_id,
                        day=forecast_day,
                        projected_net_due_usd=amount,
                        projected_adjustments_usd=0.0,
                        model_version="ce-net-v1",
                    )
                )
                records_written += 1
    except Exception:
        session.execute(delete(BillingForecast).where(BillingForecast.connection_id == connection.id))
        session.flush()
        projected_adjustment_daily = estimate_daily_adjustment_projection(session, connection.id, as_of) if truth_mode == TRUTH_MODE_EXACT else 0.0
        return write_local_billing_forecasts(
            session,
            connection.id,
            account_ids_by_aws_id.values(),
            as_of,
            projected_adjustment_daily=projected_adjustment_daily,
            model_version="billing-local-fallback-v1",
        )

    projected_adjustment_daily = 0.0
    model_version = "ce-net-v1"
    if truth_mode == TRUTH_MODE_EXACT:
        projected_adjustment_daily = estimate_daily_adjustment_projection(session, connection.id, as_of)
        model_version = "hybrid-net-v1"

    for future_day in iter_days(as_of + timedelta(days=1), month_end):
        base_amount = round_money(overall_projection.get(future_day, 0.0))
        session.add(
            BillingForecast(
                connection_id=connection.id,
                account_id=None,
                day=future_day,
                projected_net_due_usd=round_money(base_amount + projected_adjustment_daily),
                projected_adjustments_usd=round_money(projected_adjustment_daily),
                model_version=model_version,
            )
        )
        records_written += 1

    session.flush()
    return records_written


def write_local_billing_forecasts(
    session: Session,
    connection_id: int,
    account_ids: Any,
    as_of: date,
    projected_adjustment_daily: float,
    model_version: str,
) -> int:
    month_end = next_month_start(as_of) - timedelta(days=1)
    if as_of >= month_end:
        session.flush()
        return 0

    future_days = iter_days(as_of + timedelta(days=1), month_end)
    trailing_start = max(first_day_of_month(as_of), as_of - timedelta(days=13))
    overall_totals: dict[date, float] = defaultdict(float)
    records_written = 0

    for account_id in sorted(set(account_ids)):
        trailing_mean = session.scalar(
            select(func.avg(DailyBillingTotal.net_due_usd)).where(
                DailyBillingTotal.connection_id == connection_id,
                DailyBillingTotal.account_id == account_id,
                DailyBillingTotal.day >= trailing_start,
                DailyBillingTotal.day <= as_of,
            )
        ) or 0.0
        for index, future_day in enumerate(future_days, start=1):
            amount = round(float(trailing_mean) * (1 + 0.002 * index), 2)
            session.add(
                BillingForecast(
                    connection_id=connection_id,
                    account_id=account_id,
                    day=future_day,
                    projected_net_due_usd=amount,
                    projected_adjustments_usd=0.0,
                    model_version=model_version,
                )
            )
            overall_totals[future_day] += amount
            records_written += 1

    for future_day in future_days:
        session.add(
            BillingForecast(
                connection_id=connection_id,
                account_id=None,
                day=future_day,
                projected_net_due_usd=round_money(overall_totals[future_day] + projected_adjustment_daily),
                projected_adjustments_usd=round_money(projected_adjustment_daily),
                model_version=model_version,
            )
        )
        records_written += 1

    session.flush()
    return records_written


def estimate_daily_adjustment_projection(session: Session, connection_id: int, as_of: date) -> float:
    current_month_start = first_day_of_month(as_of)
    historical_daily_rates: list[float] = []

    for months_back in range(1, 4):
        month_start = add_months(current_month_start, -months_back)
        month_end = next_month_start(month_start) - timedelta(days=1)
        amount = session.scalar(
            select(
                func.sum(
                    DailyBillingTotal.tax_usd
                    + DailyBillingTotal.support_usd
                    + DailyBillingTotal.marketplace_usd
                    + DailyBillingTotal.other_adjustments_usd
                    - DailyBillingTotal.refunds_usd
                )
            ).where(
                DailyBillingTotal.connection_id == connection_id,
                DailyBillingTotal.day >= month_start,
                DailyBillingTotal.day <= month_end,
            )
        )
        if amount is None:
            continue
        historical_daily_rates.append(float(amount) / days_in_month(month_start))

    if historical_daily_rates:
        return round_money(sum(historical_daily_rates) / len(historical_daily_rates))

    elapsed_days = max((as_of - current_month_start).days + 1, 1)
    current_month_total = session.scalar(
        select(
            func.sum(
                DailyBillingTotal.tax_usd
                + DailyBillingTotal.support_usd
                + DailyBillingTotal.marketplace_usd
                + DailyBillingTotal.other_adjustments_usd
                - DailyBillingTotal.refunds_usd
            )
        ).where(
            DailyBillingTotal.connection_id == connection_id,
            DailyBillingTotal.day >= current_month_start,
            DailyBillingTotal.day <= as_of,
        )
    )
    if current_month_total is None:
        return 0.0
    return round_money(float(current_month_total) / elapsed_days)


def get_connection_account_ids_by_aws_id(session: Session, connection_id: int) -> dict[str, int]:
    rows = session.execute(
        select(ConnectionAccount.account_id)
        .where(ConnectionAccount.connection_id == connection_id)
    ).all()
    if not rows:
        return {}
    account_ids = [row.account_id for row in rows]

    return {
        aws_account_id: account_id
        for aws_account_id, account_id in session.execute(
            select(Account.aws_account_id, Account.id).where(Account.id.in_(account_ids))
        ).all()
    }


def clear_billing_data(session: Session, connection_id: int) -> None:
    session.execute(delete(BillingForecast).where(BillingForecast.connection_id == connection_id))
    session.execute(delete(DailyBillingTotal).where(DailyBillingTotal.connection_id == connection_id))


def build_demo_billing_truth(session: Session, connection: Connection, as_of: date) -> BillingSyncResult:
    clear_billing_data(session, connection.id)

    start_day = history_window_start(as_of)
    account_rows = session.execute(
        select(Account.id)
        .join(ConnectionAccount, ConnectionAccount.account_id == Account.id)
        .where(ConnectionAccount.connection_id == connection.id)
    ).all()
    account_ids = [row.id for row in account_rows]
    if not account_ids:
        session.flush()
        return BillingSyncResult(truth_mode=TRUTH_MODE_EXACT, records_written=0)

    usage_rows = session.execute(
        select(DailyAccountCost.account_id, DailyAccountCost.day, DailyAccountCost.cost_usd)
        .where(
            DailyAccountCost.connection_id == connection.id,
            DailyAccountCost.account_id.in_(account_ids),
            DailyAccountCost.day >= start_day,
            DailyAccountCost.day <= as_of,
        )
        .order_by(DailyAccountCost.day, DailyAccountCost.account_id)
    ).all()

    aggregates: dict[tuple[int | None, date], dict[str, float | str]] = {}
    daily_net_totals: dict[date, float] = defaultdict(float)

    for account_id, current_day, cost_usd in usage_rows:
        gross = round(float(cost_usd or 0.0), 2)
        credits = round(gross * (0.03 if current_day.day % 5 == 0 else 0.015), 2)
        savings = round(gross * (0.08 if current_day.weekday() < 5 else 0.06), 2)
        net_due = round(gross - credits - savings, 2)
        aggregates[(account_id, current_day)] = {
            "gross_usage_usd": gross,
            "credits_usd": credits,
            "savings_discounts_usd": savings,
            "tax_usd": 0.0,
            "support_usd": 0.0,
            "marketplace_usd": round(gross * 0.01 if current_day.day % 11 == 0 else 0.0, 2),
            "refunds_usd": 0.0,
            "other_adjustments_usd": 0.0,
            "net_due_usd": round(net_due + (round(gross * 0.01 if current_day.day % 11 == 0 else 0.0, 2)), 2),
            "source_kind": SOURCE_KIND_DEMO,
        }
        daily_net_totals[current_day] += gross

    for current_day, gross_total in daily_net_totals.items():
        support = round(1.25 if current_day.day in {1, 15} else 0.45, 2)
        tax = round(max(gross_total * 0.035, 0.0), 2)
        refund = round(0.65 if current_day.day == 7 else 0.0, 2)
        aggregates[(None, current_day)] = {
            "gross_usage_usd": 0.0,
            "credits_usd": 0.0,
            "savings_discounts_usd": 0.0,
            "tax_usd": tax,
            "support_usd": support,
            "marketplace_usd": 0.0,
            "refunds_usd": refund,
            "other_adjustments_usd": 0.0,
            "net_due_usd": round(tax + support - refund, 2),
            "source_kind": SOURCE_KIND_DEMO,
        }

    records_written = write_daily_billing_totals(session, connection.id, aggregates)
    records_written += build_demo_billing_forecasts(session, connection.id, as_of)
    return BillingSyncResult(truth_mode=TRUTH_MODE_EXACT, records_written=records_written)


def build_demo_billing_forecasts(session: Session, connection_id: int, as_of: date) -> int:
    session.execute(delete(BillingForecast).where(BillingForecast.connection_id == connection_id))
    account_ids = session.scalars(
        select(Account.id)
        .join(ConnectionAccount, ConnectionAccount.account_id == Account.id)
        .where(ConnectionAccount.connection_id == connection_id, ConnectionAccount.enabled.is_(True))
    ).all()
    shared_adjustment_run_rate = estimate_daily_adjustment_projection(session, connection_id, as_of)
    return write_local_billing_forecasts(
        session,
        connection_id,
        account_ids,
        as_of,
        projected_adjustment_daily=shared_adjustment_run_rate,
        model_version="demo-billing-v1",
    )


def rebuild_connection_billing_truth(session: Session, connection: Connection, as_of: date, ce_client: Any | None = None) -> BillingSyncResult:
    if connection.kind == "demo":
        return build_demo_billing_truth(session, connection, as_of)

    clear_billing_data(session, connection.id)
    account_ids_by_aws_id = get_connection_account_ids_by_aws_id(session, connection.id)

    if connection.billing_mode != BILLING_MODE_PAYABLE_HYBRID:
        aggregates = build_ce_net_fallback_actuals(connection, account_ids_by_aws_id, as_of, client=ce_client)
        records_written = write_daily_billing_totals(session, connection.id, aggregates)
        records_written += write_billing_forecasts(session, connection, account_ids_by_aws_id, as_of, TRUTH_MODE_APPROXIMATE, client=ce_client)
        return BillingSyncResult(
            truth_mode=TRUTH_MODE_APPROXIMATE,
            records_written=records_written,
            message="Billing truth is approximate because this connection is configured for usage-only payable estimates.",
        )

    if not billing_export_configured(connection):
        aggregates = build_ce_net_fallback_actuals(connection, account_ids_by_aws_id, as_of, client=ce_client)
        records_written = write_daily_billing_totals(session, connection.id, aggregates)
        records_written += write_billing_forecasts(session, connection, account_ids_by_aws_id, as_of, TRUTH_MODE_APPROXIMATE, client=ce_client)
        return BillingSyncResult(
            truth_mode=TRUTH_MODE_APPROXIMATE,
            records_written=records_written,
            message="Billing truth is approximate because no AWS Data Exports bucket, prefix, and region are configured for this connection.",
        )

    start_day = history_window_start(as_of)
    try:
        aws_session = build_aws_session_for_connection(connection)
        s3_client = aws_session.client("s3", region_name=connection.billing_export_region)
        exact_aggregates, latest_modified = load_data_export_aggregates(
            s3_client,
            connection.billing_export_bucket or "",
            connection.billing_export_prefix or "",
            account_ids_by_aws_id,
            start_day,
            as_of,
        )
        if exact_aggregates and latest_export_is_fresh(latest_modified):
            records_written = write_daily_billing_totals(session, connection.id, exact_aggregates)
            records_written += write_billing_forecasts(session, connection, account_ids_by_aws_id, as_of, TRUTH_MODE_EXACT)
            return BillingSyncResult(truth_mode=TRUTH_MODE_EXACT, records_written=records_written)
        warning = (
            "Billing truth is approximate because the configured AWS Data Export is stale."
            if exact_aggregates
            else "Billing truth is approximate because no readable AWS Data Export parquet rows were found in the configured prefix."
        )
    except Exception as error:
        warning = (
            "Billing truth is approximate because the AWS Data Export could not be read: "
            f"{describe_aws_error(error, 'read AWS Data Exports parquet files')}"
        )

    aggregates = build_ce_net_fallback_actuals(connection, account_ids_by_aws_id, as_of, client=ce_client)
    records_written = write_daily_billing_totals(session, connection.id, aggregates)
    records_written += write_billing_forecasts(session, connection, account_ids_by_aws_id, as_of, TRUTH_MODE_APPROXIMATE, client=ce_client)
    return BillingSyncResult(truth_mode=TRUTH_MODE_APPROXIMATE, records_written=records_written, message=warning)
