from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Anomaly,
    BillingForecast,
    Connection,
    ConnectionAccount,
    DailyAccountCost,
    DailyBillingTotal,
    DailyServiceCost,
    DailyTeamCost,
    Forecast,
    Recommendation,
    SyncRun,
    Team,
)
from app.services.billing import (
    BILLING_MODE_PAYABLE_HYBRID,
    SOURCE_KIND_DATA_EXPORT,
    TRUTH_MODE_APPROXIMATE,
    TRUTH_MODE_EXACT,
    billing_export_configured,
)

RANGE_TO_DAYS = {"30d": 30, "90d": 90, "365d": 365}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def money(value: float | None) -> float:
    return round(float(value or 0.0), 2)


def current_month_start(today: date | None = None) -> date:
    today = today or utc_today()
    return today.replace(day=1)


def day_span(start_day: date, end_day: date) -> list[date]:
    days: list[date] = []
    current_day = start_day
    while current_day <= end_day:
        days.append(current_day)
        current_day += timedelta(days=1)
    return days


def billing_truth_mode_for_connection(session: Session, connection: Connection) -> str:
    if connection.kind == "demo":
        return TRUTH_MODE_EXACT
    if connection.billing_mode != BILLING_MODE_PAYABLE_HYBRID:
        return TRUTH_MODE_APPROXIMATE
    if not billing_export_configured(connection):
        return TRUTH_MODE_APPROXIMATE

    has_exact_rows = session.scalar(
        select(DailyBillingTotal.id).where(
            DailyBillingTotal.connection_id == connection.id,
            DailyBillingTotal.source_kind == SOURCE_KIND_DATA_EXPORT,
        ).limit(1)
    )
    return TRUTH_MODE_EXACT if has_exact_rows else TRUTH_MODE_APPROXIMATE


def range_start(range_key: str, today: date | None = None) -> date:
    if range_key not in RANGE_TO_DAYS:
        raise ValueError(f"Unsupported range '{range_key}'")
    today = today or utc_today()
    return today - timedelta(days=RANGE_TO_DAYS[range_key] - 1)


def latest_connection_sync(session: Session, connection_id: int) -> SyncRun | None:
    return session.execute(
        select(SyncRun)
        .where(SyncRun.connection_id == connection_id)
        .order_by(SyncRun.finished_at.desc(), SyncRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_account_sync(session: Session, connection_id: int, account_id: int) -> SyncRun | None:
    return session.execute(
        select(SyncRun)
        .where(
            SyncRun.connection_id == connection_id,
            (SyncRun.account_id == account_id) | (SyncRun.account_id.is_(None)),
        )
        .order_by(SyncRun.finished_at.desc(), SyncRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def usage_sync_coverage(session: Session, connection_id: int, today: date | None = None) -> tuple[date, date] | None:
    today = today or utc_today()
    run = session.execute(
        select(SyncRun)
        .where(
            SyncRun.connection_id == connection_id,
            SyncRun.status.in_(("success", "partial_success")),
        )
        .order_by(SyncRun.finished_at.desc(), SyncRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not run or not run.finished_at or run.window_days < 1:
        return None

    coverage_end = min(run.finished_at.astimezone(timezone.utc).date(), today)
    coverage_start = coverage_end - timedelta(days=run.window_days - 1)
    return coverage_start, coverage_end


def build_summary_response(session: Session, connection_id: int, range_key: str) -> dict:
    today = utc_today()
    start_day = range_start(range_key, today)
    period_days = RANGE_TO_DAYS[range_key]
    previous_start = start_day - timedelta(days=period_days)
    previous_end = start_day - timedelta(days=1)

    total_cost = session.scalar(
        select(func.sum(DailyAccountCost.cost_usd)).where(
            DailyAccountCost.connection_id == connection_id,
            DailyAccountCost.day >= start_day,
            DailyAccountCost.day <= today,
        )
    )
    previous_total = session.scalar(
        select(func.sum(DailyAccountCost.cost_usd)).where(
            DailyAccountCost.connection_id == connection_id,
            DailyAccountCost.day >= previous_start,
            DailyAccountCost.day <= previous_end,
        )
    )
    forecast_total = session.scalar(
        select(func.sum(Forecast.projected_cost_usd)).where(
            Forecast.connection_id == connection_id,
            Forecast.account_id.is_(None),
            Forecast.day > today,
        )
    )
    active_accounts = session.scalar(
        select(func.count(ConnectionAccount.id)).where(
            ConnectionAccount.connection_id == connection_id,
            ConnectionAccount.enabled.is_(True),
        )
    ) or 0
    services_covered = session.scalar(
        select(func.count(func.distinct(DailyServiceCost.service_name))).where(
            DailyServiceCost.connection_id == connection_id,
            DailyServiceCost.day >= start_day,
            DailyServiceCost.day <= today,
        )
    ) or 0

    unallocated_team_id = session.scalar(select(Team.id).where(Team.name == "Unallocated"))
    unallocated_cost = 0.0
    if unallocated_team_id:
        unallocated_cost = session.scalar(
            select(func.sum(DailyTeamCost.cost_usd)).where(
                DailyTeamCost.connection_id == connection_id,
                DailyTeamCost.team_id == unallocated_team_id,
                DailyTeamCost.day >= start_day,
                DailyTeamCost.day <= today,
            )
        ) or 0.0

    daily_cost_rows = session.execute(
        select(DailyAccountCost.day, func.sum(DailyAccountCost.cost_usd))
        .where(
            DailyAccountCost.connection_id == connection_id,
            DailyAccountCost.day >= start_day,
            DailyAccountCost.day <= today,
        )
        .group_by(DailyAccountCost.day)
        .order_by(DailyAccountCost.day)
    ).all()
    daily_cost_map = {day: money(cost) for day, cost in daily_cost_rows}

    account_breakdown = session.execute(
        select(Account.id, Account.display_name, func.sum(DailyAccountCost.cost_usd))
        .join(Account, Account.id == DailyAccountCost.account_id)
        .where(
            DailyAccountCost.connection_id == connection_id,
            DailyAccountCost.day >= start_day,
            DailyAccountCost.day <= today,
        )
        .group_by(Account.id, Account.display_name)
        .order_by(func.sum(DailyAccountCost.cost_usd).desc())
    ).all()

    service_breakdown = session.execute(
        select(DailyServiceCost.service_name, func.sum(DailyServiceCost.cost_usd))
        .where(
            DailyServiceCost.connection_id == connection_id,
            DailyServiceCost.day >= start_day,
            DailyServiceCost.day <= today,
        )
        .group_by(DailyServiceCost.service_name)
        .order_by(func.sum(DailyServiceCost.cost_usd).desc())
    ).all()

    team_breakdown = session.execute(
        select(Team.name, func.sum(DailyTeamCost.cost_usd))
        .join(Team, Team.id == DailyTeamCost.team_id)
        .where(
            DailyTeamCost.connection_id == connection_id,
            DailyTeamCost.day >= start_day,
            DailyTeamCost.day <= today,
        )
        .group_by(Team.name)
        .order_by(func.sum(DailyTeamCost.cost_usd).desc())
    ).all()

    last_sync = latest_connection_sync(session, connection_id)
    delta_pct = 0.0
    if previous_total:
        delta_pct = ((float(total_cost or 0.0) - float(previous_total)) / float(previous_total)) * 100

    coverage = usage_sync_coverage(session, connection_id, today)
    if coverage:
        coverage_start, coverage_end = coverage
        daily_series = [
            {"date": day.isoformat(), "cost": daily_cost_map.get(day, 0.0)}
            for day in day_span(max(start_day, coverage_start), min(today, coverage_end))
        ]
    else:
        daily_series = [{"date": day.isoformat(), "cost": cost} for day, cost in sorted(daily_cost_map.items())]

    return {
        "connection_id": connection_id,
        "range": range_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "total_cost": money(total_cost),
            "previous_total_cost": money(previous_total),
            "delta_pct": round(delta_pct, 2),
            "forecast_total": money(forecast_total),
            "active_accounts": int(active_accounts),
            "services_covered": int(services_covered),
            "unallocated_share_pct": round((float(unallocated_cost) / float(total_cost or 1.0)) * 100, 2),
        },
        "daily_costs": daily_series,
        "cost_by_account": [{"key": account_id, "label": name, "cost": money(cost)} for account_id, name, cost in account_breakdown],
        "cost_by_service": [{"key": name, "label": name, "cost": money(cost)} for name, cost in service_breakdown],
        "cost_by_team": [{"key": name, "label": name, "cost": money(cost)} for name, cost in team_breakdown],
        "sync_status": {
            "last_run_at": last_sync.finished_at.isoformat() if last_sync and last_sync.finished_at else None,
            "status": last_sync.status if last_sync else "unknown",
            "accounts_synced": last_sync.accounts_synced if last_sync else 0,
        },
    }


def build_accounts_response(session: Session, connection_id: int) -> dict:
    today = utc_today()
    last_30_start = today - timedelta(days=29)
    last_7_start = today - timedelta(days=6)
    month_start = current_month_start(today)
    unallocated_team_id = session.scalar(select(Team.id).where(Team.name == "Unallocated"))

    rows = session.execute(
        select(Account, ConnectionAccount)
        .join(ConnectionAccount, ConnectionAccount.account_id == Account.id)
        .where(ConnectionAccount.connection_id == connection_id)
        .order_by(Account.display_name)
    ).all()

    items = []
    for account, membership in rows:
        current_30 = session.scalar(
            select(func.sum(DailyAccountCost.cost_usd)).where(
                DailyAccountCost.connection_id == connection_id,
                DailyAccountCost.account_id == account.id,
                DailyAccountCost.day >= last_30_start,
                DailyAccountCost.day <= today,
            )
        )
        last_7 = session.scalar(
            select(func.sum(DailyAccountCost.cost_usd)).where(
                DailyAccountCost.connection_id == connection_id,
                DailyAccountCost.account_id == account.id,
                DailyAccountCost.day >= last_7_start,
                DailyAccountCost.day <= today,
            )
        )
        projected = session.scalar(
            select(func.sum(Forecast.projected_cost_usd)).where(
                Forecast.connection_id == connection_id,
                Forecast.account_id == account.id,
                Forecast.day > today,
            )
        )
        gross_usage_mtd = session.scalar(
            select(func.sum(DailyBillingTotal.gross_usage_usd)).where(
                DailyBillingTotal.connection_id == connection_id,
                DailyBillingTotal.account_id == account.id,
                DailyBillingTotal.day >= month_start,
                DailyBillingTotal.day <= today,
            )
        )
        direct_net_due_mtd = session.scalar(
            select(func.sum(DailyBillingTotal.net_due_usd)).where(
                DailyBillingTotal.connection_id == connection_id,
                DailyBillingTotal.account_id == account.id,
                DailyBillingTotal.day >= month_start,
                DailyBillingTotal.day <= today,
            )
        )
        direct_net_projected_remainder = session.scalar(
            select(func.sum(BillingForecast.projected_net_due_usd)).where(
                BillingForecast.connection_id == connection_id,
                BillingForecast.account_id == account.id,
                BillingForecast.day > today,
            )
        )
        last_sync = latest_account_sync(session, connection_id, account.id)

        unallocated_share_pct = 0.0
        if unallocated_team_id and current_30:
            unallocated = session.scalar(
                select(func.sum(DailyTeamCost.cost_usd)).where(
                    DailyTeamCost.connection_id == connection_id,
                    DailyTeamCost.account_id == account.id,
                    DailyTeamCost.team_id == unallocated_team_id,
                    DailyTeamCost.day >= last_30_start,
                    DailyTeamCost.day <= today,
                )
            ) or 0.0
            unallocated_share_pct = round(float(unallocated) / float(current_30) * 100, 2)

        items.append(
            {
                "id": account.id,
                "display_name": account.display_name,
                "aws_account_id": account.aws_account_id,
                "role_arn": account.role_arn,
                "external_id": account.external_id,
                "team_tag_key": account.team_tag_key,
                "enabled": account.enabled,
                "current_30d_cost": money(current_30),
                "last_7d_cost": money(last_7),
                "forecast_total": money(projected),
                "gross_usage_mtd_usd": money(gross_usage_mtd),
                "direct_net_due_mtd_usd": money(direct_net_due_mtd),
                "direct_projected_month_end_net_due_usd": round(
                    money(direct_net_due_mtd) + money(direct_net_projected_remainder),
                    2,
                ),
                "shared_adjustments_included": False,
                "last_sync_at": last_sync.finished_at.isoformat() if last_sync and last_sync.finished_at else None,
                "last_sync_status": last_sync.status if last_sync else "never",
                "unallocated_share_pct": unallocated_share_pct,
                "membership_source": membership.membership_source,
                "is_primary": membership.is_primary,
                "membership_enabled": membership.enabled,
            }
        )

    return {"connection_id": connection_id, "items": items}


def build_services_response(session: Session, connection_id: int, range_key: str, account_id: int | None) -> dict:
    today = utc_today()
    start_day = range_start(range_key, today)

    query = select(DailyServiceCost.service_name, DailyServiceCost.day, DailyServiceCost.cost_usd).where(
        DailyServiceCost.connection_id == connection_id,
        DailyServiceCost.day >= start_day,
        DailyServiceCost.day <= today,
    )
    if account_id:
        query = query.where(DailyServiceCost.account_id == account_id)

    rows = session.execute(query.order_by(DailyServiceCost.service_name, DailyServiceCost.day)).all()
    grouped = defaultdict(list)
    for service_name, day, cost in rows:
        grouped[service_name].append((day, float(cost)))

    items = []
    for service_name, values in grouped.items():
        ordered = sorted(values, key=lambda item: item[0])
        total_cost = sum(amount for _, amount in ordered)
        latest_cost = ordered[-1][1]
        last_7 = sum(amount for day, amount in ordered if day >= today - timedelta(days=6))
        prev_7 = sum(amount for day, amount in ordered if today - timedelta(days=13) <= day <= today - timedelta(days=7))
        change_pct = ((last_7 - prev_7) / prev_7 * 100) if prev_7 else 0.0
        items.append(
            {
                "service_name": service_name,
                "total_cost": round(total_cost, 2),
                "avg_daily_cost": round(total_cost / len(ordered), 2),
                "latest_cost": round(latest_cost, 2),
                "change_pct": round(change_pct, 2),
            }
        )

    items.sort(key=lambda item: item["total_cost"], reverse=True)
    daily_series = [{"date": day.isoformat(), "service_name": service_name, "cost": money(cost)} for service_name, day, cost in rows]
    top_service = items[0]["service_name"] if items else None
    top_service_cost = items[0]["total_cost"] if items else 0.0

    return {
        "connection_id": connection_id,
        "range": range_key,
        "account_id": account_id,
        "summary": {
            "total_cost": round(sum(item["total_cost"] for item in items), 2),
            "top_service": top_service,
            "top_service_cost": round(top_service_cost, 2),
        },
        "items": items,
        "daily_series": daily_series,
    }


def build_trends_response(session: Session, connection_id: int, range_key: str, group_by: str) -> dict:
    today = utc_today()
    start_day = range_start(range_key, today)

    if group_by == "account":
        rows = session.execute(
            select(DailyAccountCost.day, Account.display_name, func.sum(DailyAccountCost.cost_usd))
            .join(Account, Account.id == DailyAccountCost.account_id)
            .where(
                DailyAccountCost.connection_id == connection_id,
                DailyAccountCost.day >= start_day,
                DailyAccountCost.day <= today,
            )
            .group_by(DailyAccountCost.day, Account.display_name)
            .order_by(DailyAccountCost.day, Account.display_name)
        ).all()
    elif group_by == "service":
        rows = session.execute(
            select(DailyServiceCost.day, DailyServiceCost.service_name, func.sum(DailyServiceCost.cost_usd))
            .where(
                DailyServiceCost.connection_id == connection_id,
                DailyServiceCost.day >= start_day,
                DailyServiceCost.day <= today,
            )
            .group_by(DailyServiceCost.day, DailyServiceCost.service_name)
            .order_by(DailyServiceCost.day, DailyServiceCost.service_name)
        ).all()
    elif group_by == "team":
        rows = session.execute(
            select(DailyTeamCost.day, Team.name, func.sum(DailyTeamCost.cost_usd))
            .join(Team, Team.id == DailyTeamCost.team_id)
            .where(
                DailyTeamCost.connection_id == connection_id,
                DailyTeamCost.day >= start_day,
                DailyTeamCost.day <= today,
            )
            .group_by(DailyTeamCost.day, Team.name)
            .order_by(DailyTeamCost.day, Team.name)
        ).all()
    else:
        raise ValueError("group_by must be one of: account, service, team")

    totals = defaultdict(float)
    cost_by_day_group: dict[tuple[date, str], float] = {}
    for day, group, amount in rows:
        numeric_amount = float(amount or 0.0)
        totals[group] += numeric_amount
        cost_by_day_group[(day, group)] = numeric_amount

    total_items = [{"group": group, "total_cost": round(total_cost, 2)} for group, total_cost in sorted(totals.items(), key=lambda item: item[1], reverse=True)]
    group_names = [item["group"] for item in total_items]
    coverage = usage_sync_coverage(session, connection_id, today)
    if coverage:
        coverage_start, coverage_end = coverage
        series = [
            {"date": day.isoformat(), "group": group, "cost": money(cost_by_day_group.get((day, group), 0.0))}
            for day in day_span(max(start_day, coverage_start), min(today, coverage_end))
            for group in group_names
        ]
    else:
        series = [{"date": day.isoformat(), "group": group, "cost": money(amount)} for (day, group), amount in sorted(cost_by_day_group.items())]
    return {
        "connection_id": connection_id,
        "range": range_key,
        "group_by": group_by,
        "series": series,
        "totals": total_items,
        "available_groups": [item["group"] for item in total_items],
    }


def build_forecast_response(session: Session, connection_id: int) -> dict:
    today = utc_today()
    month_start = current_month_start(today)
    month_label = month_start.strftime("%B %Y")

    actual_total = session.scalar(
        select(func.sum(DailyAccountCost.cost_usd)).where(
            DailyAccountCost.connection_id == connection_id,
            DailyAccountCost.day >= month_start,
            DailyAccountCost.day <= today,
        )
    )
    projected_remainder = session.scalar(
        select(func.sum(Forecast.projected_cost_usd)).where(
            Forecast.connection_id == connection_id,
            Forecast.account_id.is_(None),
            Forecast.day > today,
        )
    )

    daily_projection_rows = session.execute(
        select(Forecast.day, Forecast.projected_cost_usd)
        .where(
            Forecast.connection_id == connection_id,
            Forecast.account_id.is_(None),
            Forecast.day > today,
        )
        .order_by(Forecast.day)
    ).all()

    accounts = get_connection_accounts_for_forecast(session, connection_id)
    account_items = []
    for account in accounts:
        actual = session.scalar(
            select(func.sum(DailyAccountCost.cost_usd)).where(
                DailyAccountCost.connection_id == connection_id,
                DailyAccountCost.account_id == account.id,
                DailyAccountCost.day >= month_start,
                DailyAccountCost.day <= today,
            )
        )
        projected = session.scalar(
            select(func.sum(Forecast.projected_cost_usd)).where(
                Forecast.connection_id == connection_id,
                Forecast.account_id == account.id,
                Forecast.day > today,
            )
        )
        account_items.append(
            {
                "account_id": account.id,
                "account_name": account.display_name,
                "actual_to_date": money(actual),
                "projected_remainder": money(projected),
                "projected_total": round(money(actual) + money(projected), 2),
            }
        )

    return {
        "connection_id": connection_id,
        "month": month_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": {
            "actual_to_date": money(actual_total),
            "projected_remainder": money(projected_remainder),
            "projected_total": round(money(actual_total) + money(projected_remainder), 2),
        },
        "accounts": account_items,
        "daily_projection": [{"date": day.isoformat(), "projected_cost": money(amount)} for day, amount in daily_projection_rows],
    }


def build_billing_overview_response(session: Session, connection_id: int) -> dict:
    today = utc_today()
    month_start = current_month_start(today)
    month_label = month_start.strftime("%B %Y")
    connection = session.get(Connection, connection_id)
    if not connection:
        raise ValueError("Connection not found")

    actuals = session.execute(
        select(
            func.sum(DailyBillingTotal.gross_usage_usd),
            func.sum(DailyBillingTotal.credits_usd),
            func.sum(DailyBillingTotal.savings_discounts_usd),
            func.sum(DailyBillingTotal.tax_usd),
            func.sum(DailyBillingTotal.support_usd),
            func.sum(DailyBillingTotal.marketplace_usd),
            func.sum(DailyBillingTotal.refunds_usd),
            func.sum(DailyBillingTotal.other_adjustments_usd),
            func.sum(DailyBillingTotal.net_due_usd),
        ).where(
            DailyBillingTotal.connection_id == connection_id,
            DailyBillingTotal.day >= month_start,
            DailyBillingTotal.day <= today,
        )
    ).one()
    gross_usage, credits, savings, tax, support, marketplace, refunds, other_adjustments, actual_net_due = actuals
    credits_and_savings = money(credits) + money(savings)
    bill_adjustments = round(
        money(tax) + money(support) + money(marketplace) + money(other_adjustments) - money(refunds),
        2,
    )

    projected_usage_remainder = session.scalar(
        select(func.sum(BillingForecast.projected_net_due_usd - BillingForecast.projected_adjustments_usd)).where(
            BillingForecast.connection_id == connection_id,
            BillingForecast.account_id.is_(None),
            BillingForecast.day > today,
        )
    )
    projected_adjustments = session.scalar(
        select(func.sum(BillingForecast.projected_adjustments_usd)).where(
            BillingForecast.connection_id == connection_id,
            BillingForecast.account_id.is_(None),
            BillingForecast.day > today,
        )
    )
    projected_net_due = session.scalar(
        select(func.sum(BillingForecast.projected_net_due_usd)).where(
            BillingForecast.connection_id == connection_id,
            BillingForecast.account_id.is_(None),
            BillingForecast.day > today,
        )
    )

    actual_daily_rows = session.execute(
        select(DailyBillingTotal.day, func.sum(DailyBillingTotal.net_due_usd))
        .where(
            DailyBillingTotal.connection_id == connection_id,
            DailyBillingTotal.day >= month_start,
            DailyBillingTotal.day <= today,
        )
        .group_by(DailyBillingTotal.day)
        .order_by(DailyBillingTotal.day)
    ).all()
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    projected_daily_rows = session.execute(
        select(BillingForecast.day, BillingForecast.projected_net_due_usd)
        .where(
            BillingForecast.connection_id == connection_id,
            BillingForecast.account_id.is_(None),
            BillingForecast.day > today,
            BillingForecast.day <= month_end,
        )
        .order_by(BillingForecast.day)
    ).all()
    shared_rows = session.execute(
        select(
            func.sum(DailyBillingTotal.net_due_usd),
            func.sum(DailyBillingTotal.credits_usd + DailyBillingTotal.savings_discounts_usd + DailyBillingTotal.refunds_usd),
        ).where(
            DailyBillingTotal.connection_id == connection_id,
            DailyBillingTotal.account_id.is_(None),
            DailyBillingTotal.day >= month_start,
            DailyBillingTotal.day <= today,
        )
    ).one()
    shared_adjustments_usd, shared_offsets = shared_rows

    actual_map = {day: money(amount) for day, amount in actual_daily_rows}
    projected_map = {day: money(amount) for day, amount in projected_daily_rows}
    last_projected_day = max(projected_map.keys(), default=today)
    daily_days = day_span(month_start, max(today, last_projected_day))

    return {
        "connection_id": connection_id,
        "truth_mode": billing_truth_mode_for_connection(session, connection),
        "month": month_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "actual_to_date": {
            "gross_usage_usd": money(gross_usage),
            "credits_and_savings_usd": round(credits_and_savings, 2),
            "bill_adjustments_usd": bill_adjustments,
            "net_due_usd": money(actual_net_due),
        },
        "projected_remainder": {
            "usage_net_usd": money(projected_usage_remainder),
            "bill_adjustments_usd": money(projected_adjustments),
            "net_due_usd": money(projected_net_due),
        },
        "month_end_estimate": {
            "net_due_usd": round(money(actual_net_due) + money(projected_net_due), 2),
        },
        "daily_net_due": [
            {
                "date": day.isoformat(),
                "actual_net_due_usd": actual_map.get(day, 0.0),
                "projected_net_due_usd": projected_map.get(day, 0.0),
            }
            for day in daily_days
        ],
        "reconciliation": {
            "shared_adjustments_usd": money(shared_adjustments_usd),
            "shared_offsets_present": money(shared_offsets) > 0,
        },
    }


def get_connection_accounts_for_forecast(session: Session, connection_id: int) -> list[Account]:
    return list(
        session.scalars(
            select(Account)
            .join(ConnectionAccount, ConnectionAccount.account_id == Account.id)
            .where(ConnectionAccount.connection_id == connection_id, ConnectionAccount.enabled.is_(True))
            .order_by(Account.display_name)
        ).all()
    )


def list_recommendations_response(session: Session, connection_id: int) -> dict:
    rows = session.execute(
        select(Recommendation, Account.display_name)
        .join(Account, Account.id == Recommendation.account_id, isouter=True)
        .where(Recommendation.connection_id == connection_id)
        .order_by(Recommendation.estimated_monthly_savings_usd.desc(), Recommendation.created_at.desc())
    ).all()

    items = []
    for recommendation, account_name in rows:
        items.append(
            {
                "id": recommendation.id,
                "title": recommendation.title,
                "summary": recommendation.summary,
                "impact_level": recommendation.impact_level,
                "estimated_monthly_savings_usd": money(recommendation.estimated_monthly_savings_usd),
                "account_name": account_name,
                "service_name": recommendation.service_name,
                "status": recommendation.status,
                "created_at": recommendation.created_at.isoformat() if recommendation.created_at else None,
            }
        )

    return {"connection_id": connection_id, "items": items}


def list_anomalies_response(session: Session, connection_id: int) -> dict:
    rows = session.execute(
        select(Anomaly, Account.display_name, Team.name)
        .join(Account, Account.id == Anomaly.account_id, isouter=True)
        .join(Team, Team.id == Anomaly.team_id, isouter=True)
        .where(Anomaly.connection_id == connection_id)
        .order_by(Anomaly.detected_on.desc(), Anomaly.created_at.desc())
    ).all()

    items = []
    for anomaly, account_name, team_name in rows:
        items.append(
            {
                "id": anomaly.id,
                "kind": anomaly.kind,
                "title": anomaly.title,
                "summary": anomaly.summary,
                "severity": anomaly.severity,
                "detected_on": anomaly.detected_on.isoformat(),
                "amount_delta_usd": money(anomaly.amount_delta_usd),
                "account_name": account_name,
                "service_name": anomaly.service_name,
                "team_name": team_name,
            }
        )

    return {"connection_id": connection_id, "items": items}


def list_connections_response(session: Session) -> dict:
    connections = session.scalars(select(Connection).order_by(Connection.kind, Connection.name)).all()
    items = []
    for connection in connections:
        last_sync = latest_connection_sync(session, connection.id)
        account_count = session.scalar(
            select(func.count(ConnectionAccount.id)).where(ConnectionAccount.connection_id == connection.id)
        ) or 0
        primary_account = session.execute(
            select(Account.display_name)
            .join(ConnectionAccount, ConnectionAccount.account_id == Account.id)
            .where(ConnectionAccount.connection_id == connection.id, ConnectionAccount.is_primary.is_(True))
        ).scalar_one_or_none()
        items.append(
            {
                "id": connection.id,
                "name": connection.name,
                "kind": connection.kind,
                "enabled": connection.enabled,
                "role_arn": connection.role_arn,
                "external_id": connection.external_id,
                "billing_view_arn": connection.billing_view_arn,
                "billing_mode": connection.billing_mode,
                "billing_export_bucket": connection.billing_export_bucket,
                "billing_export_prefix": connection.billing_export_prefix,
                "billing_export_region": connection.billing_export_region,
                "billing_truth_mode": billing_truth_mode_for_connection(session, connection),
                "team_tag_key": connection.team_tag_key,
                "account_count": int(account_count),
                "primary_account_name": primary_account,
                "last_sync_at": last_sync.finished_at.isoformat() if last_sync and last_sync.finished_at else None,
                "last_sync_status": last_sync.status if last_sync else "never",
            }
        )
    return {"items": items}
