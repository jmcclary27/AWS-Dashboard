from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Anomaly,
    Connection,
    ConnectionAccount,
    DailyAccountCost,
    DailyServiceCost,
    DailyTeamCost,
    Forecast,
    Recommendation,
    SyncRun,
    Team,
)

RANGE_TO_DAYS = {"30d": 30, "90d": 90, "365d": 365}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def money(value: float | None) -> float:
    return round(float(value or 0.0), 2)


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

    daily_costs = session.execute(
        select(DailyAccountCost.day, func.sum(DailyAccountCost.cost_usd))
        .where(
            DailyAccountCost.connection_id == connection_id,
            DailyAccountCost.day >= start_day,
            DailyAccountCost.day <= today,
        )
        .group_by(DailyAccountCost.day)
        .order_by(DailyAccountCost.day)
    ).all()

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
        "daily_costs": [{"date": day.isoformat(), "cost": money(cost)} for day, cost in daily_costs],
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
    series = []
    for day, group, amount in rows:
        totals[group] += float(amount or 0.0)
        series.append({"date": day.isoformat(), "group": group, "cost": money(amount)})

    total_items = [{"group": group, "total_cost": round(total_cost, 2)} for group, total_cost in sorted(totals.items(), key=lambda item: item[1], reverse=True)]
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
    month_start = today.replace(day=1)
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
                "team_tag_key": connection.team_tag_key,
                "account_count": int(account_count),
                "primary_account_name": primary_account,
                "last_sync_at": last_sync.finished_at.isoformat() if last_sync and last_sync.finished_at else None,
                "last_sync_status": last_sync.status if last_sync else "never",
            }
        )
    return {"items": items}
