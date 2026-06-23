import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Anomaly,
    AppSetting,
    DailyAccountCost,
    DailyServiceCost,
    DailyTeamCost,
    Forecast,
    Recommendation,
    SyncRun,
    Team,
    TeamAlias,
)

DEFAULT_SERVICE_WEIGHTS = {
    "Amazon EC2": 0.22,
    "Amazon RDS": 0.14,
    "Amazon S3": 0.11,
    "AWS Lambda": 0.08,
    "Amazon CloudFront": 0.07,
    "Amazon DynamoDB": 0.10,
    "Amazon ECS": 0.10,
    "Amazon ElastiCache": 0.07,
    "Amazon CloudWatch": 0.06,
    "Amazon EKS": 0.05,
}

DEFAULT_TEAMS = [
    {"name": "Platform", "is_protected": False, "aliases": ["platform", "core-platform", "ops"]},
    {"name": "Data", "is_protected": False, "aliases": ["data", "ml", "analytics"]},
    {"name": "Growth", "is_protected": False, "aliases": ["growth", "marketing", "acquisition"]},
    {"name": "Security", "is_protected": False, "aliases": ["security", "secops", "identity"]},
    {"name": "Finance", "is_protected": False, "aliases": ["finance", "finops"]},
    {"name": "Unallocated", "is_protected": True, "aliases": ["", "unknown", "unallocated"]},
]

DEFAULT_ACCOUNT_PROFILES = [
    {
        "display_name": "Atlas Retail Prod",
        "aws_account_id": "114455667788",
        "base_cost": 540.0,
        "trend": 0.0024,
        "volatility": 0.08,
        "service_bias": {"Amazon EC2": 1.25, "Amazon RDS": 1.15, "Amazon CloudFront": 1.12},
        "team_weights": {
            "Growth": 0.32,
            "Platform": 0.24,
            "Data": 0.18,
            "Security": 0.10,
            "Finance": 0.10,
            "Unallocated": 0.06,
        },
        "spike_days": {5, 19, 28},
    },
    {
        "display_name": "Atlas Data Platform",
        "aws_account_id": "223344556677",
        "base_cost": 410.0,
        "trend": 0.0019,
        "volatility": 0.07,
        "service_bias": {"Amazon EKS": 1.30, "Amazon S3": 1.22, "Amazon DynamoDB": 1.18},
        "team_weights": {
            "Data": 0.41,
            "Platform": 0.24,
            "Security": 0.12,
            "Growth": 0.08,
            "Finance": 0.08,
            "Unallocated": 0.07,
        },
        "spike_days": {7, 15, 26},
    },
    {
        "display_name": "Beacon Growth Sandbox",
        "aws_account_id": "334455667788",
        "base_cost": 225.0,
        "trend": 0.0031,
        "volatility": 0.12,
        "service_bias": {"AWS Lambda": 1.26, "Amazon CloudFront": 1.28, "Amazon S3": 1.10},
        "team_weights": {
            "Growth": 0.45,
            "Platform": 0.16,
            "Data": 0.12,
            "Security": 0.08,
            "Finance": 0.05,
            "Unallocated": 0.14,
        },
        "spike_days": {3, 11, 24},
    },
    {
        "display_name": "Cedar Security Shared",
        "aws_account_id": "445566778899",
        "base_cost": 275.0,
        "trend": 0.0013,
        "volatility": 0.06,
        "service_bias": {"Amazon EC2": 1.12, "Amazon CloudWatch": 1.32, "Amazon ElastiCache": 1.08},
        "team_weights": {
            "Security": 0.38,
            "Platform": 0.23,
            "Data": 0.11,
            "Growth": 0.07,
            "Finance": 0.11,
            "Unallocated": 0.10,
        },
        "spike_days": {9, 16, 29},
    },
]


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def slugify(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def iter_days(start_day: date, end_day: date):
    cursor = start_day
    while cursor <= end_day:
        yield cursor
        cursor += timedelta(days=1)


def allocate_amounts(total: float, weights: dict[str, float], rng: random.Random, jitter: float = 0.12) -> dict[str, float]:
    adjusted = {}
    for name, weight in weights.items():
        adjusted[name] = max(weight * (1 + rng.uniform(-jitter, jitter)), 0.01)

    total_weight = sum(adjusted.values())
    keys = list(adjusted.keys())
    allocations: dict[str, float] = {}
    remainder = round(total, 2)

    for index, key in enumerate(keys):
        if index == len(keys) - 1:
            amount = round(remainder, 2)
        else:
            amount = round(total * adjusted[key] / total_weight, 2)
            remainder = round(remainder - amount, 2)
        allocations[key] = max(amount, 0.0)

    return allocations


def apply_biases(base_weights: dict[str, float], service_bias: dict[str, float], current_day: date) -> dict[str, float]:
    weights = {service: weight * service_bias.get(service, 1.0) for service, weight in base_weights.items()}
    if current_day.day >= 25:
        weights["Amazon S3"] *= 1.08
        weights["Amazon CloudWatch"] *= 1.05
    if current_day.weekday() >= 5:
        weights["AWS Lambda"] *= 1.06
        weights["Amazon CloudFront"] *= 1.04
    return weights


def build_profile(account: Account) -> dict:
    explicit = next((profile for profile in DEFAULT_ACCOUNT_PROFILES if profile["aws_account_id"] == account.aws_account_id), None)
    if explicit:
        return explicit

    seed = sum(ord(character) for character in account.aws_account_id)
    rng = random.Random(seed)
    services = list(DEFAULT_SERVICE_WEIGHTS)
    chosen = rng.sample(services, 3)
    bias = {service: 1.0 for service in services}
    for service in chosen:
        bias[service] = round(1.12 + rng.random() * 0.25, 2)

    team_names = ["Platform", "Data", "Growth", "Security", "Finance"]
    weights = {team: round(0.10 + rng.random() * 0.18, 2) for team in team_names}
    unallocated = round(0.06 + rng.random() * 0.06, 2)
    total = sum(weights.values()) + unallocated
    normalized = {team: weight / total for team, weight in weights.items()}
    normalized["Unallocated"] = unallocated / total

    return {
        "display_name": account.display_name,
        "aws_account_id": account.aws_account_id,
        "base_cost": 180.0 + rng.randint(0, 260),
        "trend": 0.001 + rng.random() * 0.0025,
        "volatility": 0.05 + rng.random() * 0.07,
        "service_bias": bias,
        "team_weights": normalized,
        "spike_days": {3 + seed % 7, 13 + seed % 9, 22 + seed % 6},
    }


def ensure_reference_data(session: Session) -> tuple[list[Account], dict[str, int]]:
    existing_teams = {team.name: team for team in session.scalars(select(Team)).all()}
    for team_config in DEFAULT_TEAMS:
        team = existing_teams.get(team_config["name"])
        if not team:
            team = Team(
                name=team_config["name"],
                slug=slugify(team_config["name"]),
                is_protected=team_config["is_protected"],
            )
            session.add(team)
            session.flush()
            existing_teams[team.name] = team

        known_aliases = set(
            session.scalars(select(TeamAlias.alias).where(TeamAlias.team_id == team.id)).all()
        )
        for alias in team_config["aliases"]:
            if alias not in known_aliases:
                session.add(TeamAlias(team_id=team.id, alias=alias))

    existing_accounts = {account.aws_account_id: account for account in session.scalars(select(Account)).all()}
    for profile in DEFAULT_ACCOUNT_PROFILES:
        if profile["aws_account_id"] not in existing_accounts:
            account = Account(
                display_name=profile["display_name"],
                aws_account_id=profile["aws_account_id"],
                team_tag_key="Team",
                enabled=True,
            )
            session.add(account)
            existing_accounts[profile["aws_account_id"]] = account

    if not session.get(AppSetting, "default_team_tag_key"):
        session.add(
            AppSetting(
                key="default_team_tag_key",
                value="Team",
                description="Default AWS cost allocation tag key",
            )
        )

    session.flush()
    accounts = session.scalars(select(Account).order_by(Account.display_name)).all()
    team_ids = {team.name: team.id for team in session.scalars(select(Team)).all()}
    return accounts, team_ids


def reset_demo_dataset(session: Session, days: int = 90) -> None:
    accounts, team_ids = ensure_reference_data(session)

    for model in (Forecast, Anomaly, Recommendation, SyncRun, DailyServiceCost, DailyTeamCost, DailyAccountCost):
        session.execute(delete(model))

    end_day = utc_today()
    start_day = end_day - timedelta(days=max(days - 1, 0))
    records_written = generate_daily_costs(session, accounts, team_ids, start_day, end_day, variant_seed=0)
    rebuild_derived_tables(session, end_day)

    for account in accounts:
        session.add(
            SyncRun(
                account_id=account.id,
                sync_type="seed",
                status="success",
                message="Initial fake dataset seeded",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                records_written=records_written,
            )
        )

    session.commit()


def refresh_recent_demo_data(session: Session, account_ids: list[int] | None = None, days: int = 14) -> dict[str, int]:
    accounts = session.scalars(select(Account).order_by(Account.display_name)).all()
    if account_ids:
        target_accounts = [account for account in accounts if account.id in account_ids]
    else:
        target_accounts = [account for account in accounts if account.enabled]

    if not target_accounts:
        return {"accounts_synced": 0, "records_written": 0}

    _, team_ids = ensure_reference_data(session)
    end_day = utc_today()
    start_day = end_day - timedelta(days=max(days - 1, 0))

    account_id_set = [account.id for account in target_accounts]
    session.execute(
        delete(DailyAccountCost).where(
            DailyAccountCost.account_id.in_(account_id_set),
            DailyAccountCost.day >= start_day,
            DailyAccountCost.day <= end_day,
        )
    )
    session.execute(
        delete(DailyServiceCost).where(
            DailyServiceCost.account_id.in_(account_id_set),
            DailyServiceCost.day >= start_day,
            DailyServiceCost.day <= end_day,
        )
    )
    session.execute(
        delete(DailyTeamCost).where(
            DailyTeamCost.account_id.in_(account_id_set),
            DailyTeamCost.day >= start_day,
            DailyTeamCost.day <= end_day,
        )
    )

    variant_seed = len(session.scalars(select(SyncRun.id)).all()) + days
    records_written = generate_daily_costs(
        session,
        target_accounts,
        team_ids,
        start_day,
        end_day,
        variant_seed=variant_seed,
    )
    rebuild_derived_tables(session, end_day)

    timestamp = datetime.now(timezone.utc)
    for account in target_accounts:
        session.add(
            SyncRun(
                account_id=account.id,
                sync_type="manual-demo",
                status="success",
                message=f"Refreshed {days} days of demo data",
                started_at=timestamp,
                finished_at=timestamp,
                records_written=records_written,
            )
        )

    session.commit()
    return {"accounts_synced": len(target_accounts), "records_written": records_written}


def generate_daily_costs(
    session: Session,
    accounts: list[Account],
    team_ids: dict[str, int],
    start_day: date,
    end_day: date,
    variant_seed: int = 0,
) -> int:
    records_written = 0

    for account in accounts:
        profile = build_profile(account)
        rng = random.Random(int(account.aws_account_id[-6:]) + variant_seed)
        for current_day in iter_days(start_day, end_day):
            day_index = current_day.toordinal()
            seasonal = 1 + 0.06 * math.sin(day_index / 4.0) + 0.04 * math.cos(day_index / 8.5)
            growth = 1 + profile["trend"] * ((current_day - start_day).days + 1)
            weekday_factor = 0.93 if current_day.weekday() >= 5 else 1.03
            noise = 1 + rng.uniform(-profile["volatility"], profile["volatility"])

            total_cost = profile["base_cost"] * seasonal * growth * weekday_factor * noise
            if current_day.day in profile["spike_days"]:
                total_cost *= 1.18
            if current_day.weekday() == 0 and "Growth" in account.display_name:
                total_cost *= 1.05

            total_cost = round(max(total_cost, 55.0), 2)
            service_weights = apply_biases(DEFAULT_SERVICE_WEIGHTS, profile["service_bias"], current_day)
            service_allocations = allocate_amounts(total_cost, service_weights, rng, jitter=0.18)
            account_total = round(sum(service_allocations.values()), 2)

            session.add(DailyAccountCost(account_id=account.id, day=current_day, cost_usd=account_total))
            records_written += 1

            for service_name, amount in service_allocations.items():
                session.add(
                    DailyServiceCost(
                        account_id=account.id,
                        day=current_day,
                        service_name=service_name,
                        cost_usd=amount,
                    )
                )
                records_written += 1

            team_allocations = allocate_amounts(account_total, profile["team_weights"], rng, jitter=0.14)
            for team_name, amount in team_allocations.items():
                session.add(
                    DailyTeamCost(
                        account_id=account.id,
                        team_id=team_ids[team_name],
                        day=current_day,
                        cost_usd=amount,
                    )
                )
                records_written += 1

    session.flush()
    return records_written


def rebuild_derived_tables(session: Session, as_of: date | None = None) -> None:
    as_of = as_of or utc_today()
    rebuild_forecasts(session, as_of)
    rebuild_anomalies(session, as_of)
    rebuild_recommendations(session, as_of)
    session.flush()


def rebuild_forecasts(session: Session, as_of: date) -> None:
    session.execute(delete(Forecast))
    month_start = as_of.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month - timedelta(days=1)

    future_days = list(iter_days(as_of + timedelta(days=1), month_end)) if as_of < month_end else []
    overall_totals = defaultdict(float)
    accounts = session.scalars(select(Account).where(Account.enabled.is_(True)).order_by(Account.display_name)).all()

    for account in accounts:
        trailing_start = max(month_start, as_of - timedelta(days=13))
        trailing_mean = (
            session.scalar(
                select(func.avg(DailyAccountCost.cost_usd)).where(
                    DailyAccountCost.account_id == account.id,
                    DailyAccountCost.day >= trailing_start,
                    DailyAccountCost.day <= as_of,
                )
            )
            or 0.0
        )

        if trailing_mean == 0:
            continue

        for index, future_day in enumerate(future_days, start=1):
            projection = round(float(trailing_mean) * (1 + 0.002 * index), 2)
            session.add(
                Forecast(
                    account_id=account.id,
                    day=future_day,
                    projected_cost_usd=projection,
                    model_version="demo-v1",
                )
            )
            overall_totals[future_day] += projection

    for future_day, amount in overall_totals.items():
        session.add(Forecast(account_id=None, day=future_day, projected_cost_usd=round(amount, 2), model_version="demo-v1"))


def rebuild_anomalies(session: Session, as_of: date) -> None:
    session.execute(delete(Anomaly))

    service_rows = session.execute(
        select(
            DailyServiceCost.account_id,
            Account.display_name,
            DailyServiceCost.service_name,
            DailyServiceCost.day,
            DailyServiceCost.cost_usd,
        )
        .join(Account, Account.id == DailyServiceCost.account_id)
        .where(DailyServiceCost.day >= as_of - timedelta(days=14), DailyServiceCost.day <= as_of)
        .order_by(DailyServiceCost.account_id, DailyServiceCost.service_name, DailyServiceCost.day)
    ).all()

    grouped_services = defaultdict(list)
    for row in service_rows:
        grouped_services[(row.account_id, row.display_name, row.service_name)].append((row.day, float(row.cost_usd)))

    for (account_id, display_name, service_name), items in grouped_services.items():
        if len(items) < 8:
            continue
        ordered = sorted(items, key=lambda item: item[0])
        current_cost = ordered[-1][1]
        trailing_average = sum(cost for _, cost in ordered[-8:-1]) / 7
        delta = current_cost - trailing_average
        if trailing_average > 0 and current_cost > trailing_average * 1.3 and delta >= 25:
            session.add(
                Anomaly(
                    kind="daily_spike",
                    title=f"{service_name} spiked in {display_name}",
                    summary=f"Current daily cost is {current_cost:.2f} USD versus a trailing 7-day average of {trailing_average:.2f} USD.",
                    severity="high" if delta >= 60 else "medium",
                    detected_on=ordered[-1][0],
                    account_id=account_id,
                    service_name=service_name,
                    amount_delta_usd=round(delta, 2),
                    metadata_json={"rule": "daily_spike"},
                )
            )

    team_rows = session.execute(
        select(Team.name, DailyTeamCost.day, func.sum(DailyTeamCost.cost_usd))
        .join(Team, Team.id == DailyTeamCost.team_id)
        .where(DailyTeamCost.day >= as_of - timedelta(days=27), DailyTeamCost.day <= as_of)
        .group_by(Team.name, DailyTeamCost.day)
    ).all()

    grouped_teams = defaultdict(list)
    for team_name, team_day, amount in team_rows:
        grouped_teams[team_name].append((team_day, float(amount or 0.0)))

    team_lookup = {team.name: team.id for team in session.scalars(select(Team)).all()}
    for team_name, items in grouped_teams.items():
        if team_name == "Unallocated" or len(items) < 14:
            continue
        ordered = sorted(items, key=lambda item: item[0])
        trailing = sum(cost for _, cost in ordered[-14:]) / 14
        prior = sum(cost for _, cost in ordered[:14]) / 14
        if prior > 0 and trailing > prior * 1.2:
            session.add(
                Anomaly(
                    kind="team_growth",
                    title=f"{team_name} spend is trending up",
                    summary=f"Trailing 14-day average is {trailing:.2f} USD against a prior 14-day average of {prior:.2f} USD.",
                    severity="medium",
                    detected_on=ordered[-1][0],
                    team_id=team_lookup[team_name],
                    amount_delta_usd=round(trailing - prior, 2),
                    metadata_json={"rule": "team_growth"},
                )
            )

    unallocated_team_id = team_lookup["Unallocated"]
    account_rows = session.scalars(select(Account).order_by(Account.display_name)).all()
    for account in account_rows:
        total = (
            session.scalar(
                select(func.sum(DailyAccountCost.cost_usd)).where(
                    DailyAccountCost.account_id == account.id,
                    DailyAccountCost.day >= as_of - timedelta(days=13),
                    DailyAccountCost.day <= as_of,
                )
            )
            or 0.0
        )
        unallocated = (
            session.scalar(
                select(func.sum(DailyTeamCost.cost_usd)).where(
                    DailyTeamCost.account_id == account.id,
                    DailyTeamCost.team_id == unallocated_team_id,
                    DailyTeamCost.day >= as_of - timedelta(days=13),
                    DailyTeamCost.day <= as_of,
                )
            )
            or 0.0
        )
        if total and (float(unallocated) / float(total)) >= 0.12:
            session.add(
                Anomaly(
                    kind="unallocated_warning",
                    title=f"{account.display_name} has elevated unallocated spend",
                    summary=f"Unallocated spend accounts for {(float(unallocated) / float(total)) * 100:.1f}% of the last 14 days.",
                    severity="medium",
                    detected_on=as_of,
                    account_id=account.id,
                    team_id=unallocated_team_id,
                    amount_delta_usd=round(float(unallocated), 2),
                    metadata_json={"rule": "unallocated_share"},
                )
            )


def recommendation_copy(service_name: str) -> tuple[str, str]:
    if service_name == "Amazon EC2":
        return ("Review EC2 rightsizing", "Check instance families, idle capacity, and schedule non-prod downtime.")
    if service_name == "Amazon RDS":
        return ("Tune RDS sizing and reservations", "Evaluate storage class, reserved capacity, and read replica usage.")
    if service_name == "Amazon S3":
        return ("Audit S3 lifecycle policies", "Move colder objects to cheaper tiers and expire obsolete artifacts.")
    if service_name in {"Amazon EKS", "Amazon ECS"}:
        return ("Right-size container workloads", "Inspect cluster utilization and consolidate underused services.")
    return ("Inspect steady service spend", "Validate whether baseline usage and attached resources still match demand.")


def rebuild_recommendations(session: Session, as_of: date) -> None:
    session.execute(delete(Recommendation))

    last_30_start = as_of - timedelta(days=29)
    service_rows = session.execute(
        select(
            DailyServiceCost.account_id,
            Account.display_name,
            DailyServiceCost.service_name,
            func.sum(DailyServiceCost.cost_usd).label("total_cost"),
            func.avg(DailyServiceCost.cost_usd).label("avg_cost"),
        )
        .join(Account, Account.id == DailyServiceCost.account_id)
        .where(DailyServiceCost.day >= last_30_start, DailyServiceCost.day <= as_of)
        .group_by(DailyServiceCost.account_id, Account.display_name, DailyServiceCost.service_name)
        .order_by(func.sum(DailyServiceCost.cost_usd).desc())
    ).all()

    created = 0
    for account_id, display_name, service_name, total_cost, avg_cost in service_rows:
        if created >= 6:
            break
        monthly_cost = float(total_cost or 0.0)
        if monthly_cost < 100:
            continue
        title, summary = recommendation_copy(service_name)
        session.add(
            Recommendation(
                title=f"{title} for {display_name}",
                summary=f"{summary} Current 30-day spend for {service_name} is {monthly_cost:.2f} USD.",
                impact_level="high" if monthly_cost >= 500 else "medium",
                estimated_monthly_savings_usd=round(float(avg_cost or 0.0) * 3.5, 2),
                account_id=account_id,
                service_name=service_name,
                status="open",
            )
        )
        created += 1

    team_lookup = {team.name: team.id for team in session.scalars(select(Team)).all()}
    unallocated_team_id = team_lookup["Unallocated"]
    accounts = session.scalars(select(Account).order_by(Account.display_name)).all()
    for account in accounts:
        total = (
            session.scalar(
                select(func.sum(DailyAccountCost.cost_usd)).where(
                    DailyAccountCost.account_id == account.id,
                    DailyAccountCost.day >= last_30_start,
                    DailyAccountCost.day <= as_of,
                )
            )
            or 0.0
        )
        unallocated = (
            session.scalar(
                select(func.sum(DailyTeamCost.cost_usd)).where(
                    DailyTeamCost.account_id == account.id,
                    DailyTeamCost.team_id == unallocated_team_id,
                    DailyTeamCost.day >= last_30_start,
                    DailyTeamCost.day <= as_of,
                )
            )
            or 0.0
        )
        if total and float(unallocated) / float(total) >= 0.10:
            session.add(
                Recommendation(
                    title=f"Reduce unallocated tagging in {account.display_name}",
                    summary="Activate or normalize the configured team cost allocation tag so spend stops rolling into Unallocated.",
                    impact_level="medium",
                    estimated_monthly_savings_usd=round(float(unallocated) * 0.08, 2),
                    account_id=account.id,
                    service_name=None,
                    status="open",
                )
            )

