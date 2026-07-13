from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from sqlalchemy import select

from app.db.models import Account, BillingForecast, Connection, ConnectionAccount, DailyAccountCost, DailyBillingTotal, SyncRun
from app.db.seed import ensure_reference_data
from app.services.billing import SOURCE_KIND_DATA_EXPORT, aggregate_data_export_rows
from app.services.analytics import (
    build_accounts_response,
    build_billing_overview_response,
    build_summary_response,
    build_trends_response,
)


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session)


def test_aggregate_data_export_rows_classifies_offsets_and_adjustments() -> None:
    today = datetime.now(timezone.utc).date()
    rows = [
        {
            "line_item_usage_account_id": "111111111111",
            "line_item_usage_start_date": today.isoformat(),
            "line_item_line_item_type": "Usage",
            "line_item_unblended_cost": "10.00",
            "line_item_net_unblended_cost": "8.00",
            "product_product_name": "Amazon EC2",
        },
        {
            "line_item_usage_account_id": "111111111111",
            "line_item_usage_start_date": today.isoformat(),
            "line_item_line_item_type": "Credit",
            "line_item_unblended_cost": "0.00",
            "line_item_net_unblended_cost": "-1.50",
            "product_product_name": "Credit",
        },
        {
            "line_item_usage_account_id": "111111111111",
            "line_item_usage_start_date": today.isoformat(),
            "line_item_line_item_type": "Tax",
            "line_item_unblended_cost": "0.50",
            "line_item_net_unblended_cost": "0.50",
            "product_product_name": "Tax",
        },
        {
            "line_item_usage_account_id": "111111111111",
            "line_item_usage_start_date": today.isoformat(),
            "line_item_line_item_type": "Fee",
            "line_item_unblended_cost": "1.00",
            "line_item_net_unblended_cost": "1.00",
            "product_product_name": "AWS Support (Business)",
            "bill_billing_entity": "AWS",
        },
        {
            "line_item_usage_start_date": today.isoformat(),
            "line_item_line_item_type": "Refund",
            "line_item_unblended_cost": "0.00",
            "line_item_net_unblended_cost": "-0.25",
            "product_product_name": "Refund",
        },
    ]

    aggregates = aggregate_data_export_rows(
        rows,
        account_ids_by_aws_id={"111111111111": 7},
        start_day=today - timedelta(days=1),
        end_day=today,
    )

    account_bucket = aggregates[(7, today)]
    shared_bucket = aggregates[(None, today)]

    assert account_bucket["gross_usage_usd"] == 10.0
    assert account_bucket["credits_usd"] == 1.5
    assert account_bucket["savings_discounts_usd"] == 2.0
    assert account_bucket["tax_usd"] == 0.5
    assert account_bucket["support_usd"] == 1.0
    assert account_bucket["net_due_usd"] == 8.0
    assert shared_bucket["refunds_usd"] == 0.25
    assert shared_bucket["net_due_usd"] == -0.25


def test_build_billing_overview_response_prefers_exact_truth() -> None:
    session_factory = make_session_factory()
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)

    with session_factory() as session:
        demo_connection, accounts, _ = ensure_reference_data(session)
        account = accounts[0]
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Exact Billing",
            kind="account_role",
            enabled=True,
            role_arn="arn:aws:iam::111111111111:role/CostRead",
            billing_mode="payable_hybrid",
            billing_export_bucket="exports-bucket",
            billing_export_prefix="cur/",
            billing_export_region="us-east-1",
            team_tag_key="Team",
        )
        session.add(connection)
        session.flush()
        session.add(
            ConnectionAccount(
                connection_id=connection.id,
                account_id=account.id,
                membership_source="manual",
                is_primary=True,
                enabled=True,
            )
        )
        session.add(
            DailyBillingTotal(
                connection_id=connection.id,
                account_id=account.id,
                day=today,
                gross_usage_usd=12.0,
                credits_usd=1.5,
                savings_discounts_usd=2.5,
                tax_usd=0.3,
                support_usd=0.2,
                marketplace_usd=0.0,
                refunds_usd=0.0,
                other_adjustments_usd=0.0,
                net_due_usd=8.5,
                source_kind=SOURCE_KIND_DATA_EXPORT,
            )
        )
        session.add(
            DailyBillingTotal(
                connection_id=connection.id,
                account_id=None,
                day=today,
                gross_usage_usd=0.0,
                credits_usd=0.0,
                savings_discounts_usd=0.0,
                tax_usd=0.0,
                support_usd=0.4,
                marketplace_usd=0.0,
                refunds_usd=0.1,
                other_adjustments_usd=0.0,
                net_due_usd=0.3,
                source_kind=SOURCE_KIND_DATA_EXPORT,
            )
        )
        session.add(
            BillingForecast(
                connection_id=connection.id,
                account_id=None,
                day=tomorrow,
                projected_net_due_usd=4.25,
                projected_adjustments_usd=0.25,
                model_version="hybrid-net-v1",
            )
        )
        session.commit()

        payload = build_billing_overview_response(session, connection.id)

    assert payload["truth_mode"] == "exact"
    assert payload["actual_to_date"]["gross_usage_usd"] == 12.0
    assert payload["actual_to_date"]["credits_and_savings_usd"] == 4.0
    assert payload["actual_to_date"]["bill_adjustments_usd"] == 0.8
    assert payload["actual_to_date"]["net_due_usd"] == 8.8
    assert payload["projected_remainder"]["usage_net_usd"] == 4.0
    assert payload["projected_remainder"]["bill_adjustments_usd"] == 0.25
    assert payload["projected_remainder"]["net_due_usd"] == 4.25
    assert payload["month_end_estimate"]["net_due_usd"] == 13.05
    assert payload["reconciliation"]["shared_adjustments_usd"] == 0.3
    assert payload["reconciliation"]["shared_offsets_present"] is True


def test_build_accounts_response_includes_direct_payable_fields() -> None:
    session_factory = make_session_factory()
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)

    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        account = session.scalars(select(Account).limit(1)).first()
        assert account is not None
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Direct Billing",
            kind="account_role",
            enabled=True,
            role_arn="arn:aws:iam::111111111111:role/CostRead",
            billing_mode="payable_hybrid",
            team_tag_key="Team",
        )
        session.add(connection)
        session.flush()
        session.add(
            ConnectionAccount(
                connection_id=connection.id,
                account_id=account.id,
                membership_source="manual",
                is_primary=True,
                enabled=True,
            )
        )
        session.add(
            DailyBillingTotal(
                connection_id=connection.id,
                account_id=account.id,
                day=today,
                gross_usage_usd=9.0,
                credits_usd=1.0,
                savings_discounts_usd=1.0,
                tax_usd=0.0,
                support_usd=0.0,
                marketplace_usd=0.0,
                refunds_usd=0.0,
                other_adjustments_usd=0.0,
                net_due_usd=7.0,
                source_kind=SOURCE_KIND_DATA_EXPORT,
            )
        )
        session.add(
            BillingForecast(
                connection_id=connection.id,
                account_id=account.id,
                day=tomorrow,
                projected_net_due_usd=2.5,
                projected_adjustments_usd=0.0,
                model_version="ce-net-v1",
            )
        )
        session.commit()

        payload = build_accounts_response(session, connection.id)

    item = payload["items"][0]
    assert item["gross_usage_mtd_usd"] == 9.0
    assert item["direct_net_due_mtd_usd"] == 7.0
    assert item["direct_projected_month_end_net_due_usd"] == 9.5
    assert item["shared_adjustments_included"] is False


def test_build_summary_response_zero_fills_requested_range() -> None:
    session_factory = make_session_factory()
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=29)

    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        account = session.scalars(select(Account).limit(1)).first()
        assert account is not None
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Summary Fill",
            kind="account_role",
            enabled=True,
            role_arn="arn:aws:iam::111111111111:role/CostRead",
            team_tag_key="Team",
        )
        session.add(connection)
        session.flush()
        session.add(
            ConnectionAccount(
                connection_id=connection.id,
                account_id=account.id,
                membership_source="manual",
                is_primary=True,
                enabled=True,
            )
        )
        session.add(
            DailyAccountCost(
                connection_id=connection.id,
                account_id=account.id,
                day=today,
                cost_usd=5.0,
            )
        )
        session.add(
            SyncRun(
                connection_id=connection.id,
                sync_type=connection.kind,
                status="success",
                window_days=30,
                accounts_synced=1,
                records_written=1,
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

        payload = build_summary_response(session, connection.id, "30d")

    assert len(payload["daily_costs"]) == 30
    assert payload["daily_costs"][0]["date"] == start_day.isoformat()
    assert payload["daily_costs"][-1] == {"date": today.isoformat(), "cost": 5.0}


def test_build_trends_response_zero_fills_missing_days() -> None:
    session_factory = make_session_factory()
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=29)

    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        account = session.scalars(select(Account).limit(1)).first()
        assert account is not None
        account_name = account.display_name
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Trend Fill",
            kind="account_role",
            enabled=True,
            role_arn="arn:aws:iam::111111111111:role/CostRead",
            team_tag_key="Team",
        )
        session.add(connection)
        session.flush()
        session.add(
            ConnectionAccount(
                connection_id=connection.id,
                account_id=account.id,
                membership_source="manual",
                is_primary=True,
                enabled=True,
            )
        )
        session.add(
            DailyAccountCost(
                connection_id=connection.id,
                account_id=account.id,
                day=today,
                cost_usd=7.0,
            )
        )
        session.add(
            SyncRun(
                connection_id=connection.id,
                sync_type=connection.kind,
                status="success",
                window_days=30,
                accounts_synced=1,
                records_written=1,
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

        payload = build_trends_response(session, connection.id, "30d", "account")

    assert payload["available_groups"] == [account_name]
    assert len(payload["series"]) == 30
    assert payload["series"][0] == {"date": start_day.isoformat(), "group": account_name, "cost": 0.0}
    assert payload["series"][-1] == {"date": today.isoformat(), "group": account_name, "cost": 7.0}


def test_build_billing_overview_response_zero_fills_month_start() -> None:
    session_factory = make_session_factory()
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1)

    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        account = session.scalars(select(Account).limit(1)).first()
        assert account is not None
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Billing Fill",
            kind="account_role",
            enabled=True,
            role_arn="arn:aws:iam::111111111111:role/CostRead",
            billing_mode="payable_hybrid",
            billing_export_bucket="exports-bucket",
            billing_export_prefix="cur/",
            billing_export_region="us-east-1",
            team_tag_key="Team",
        )
        session.add(connection)
        session.flush()
        session.add(
            ConnectionAccount(
                connection_id=connection.id,
                account_id=account.id,
                membership_source="manual",
                is_primary=True,
                enabled=True,
            )
        )
        session.add(
            DailyBillingTotal(
                connection_id=connection.id,
                account_id=account.id,
                day=today,
                gross_usage_usd=3.0,
                credits_usd=0.5,
                savings_discounts_usd=0.5,
                tax_usd=0.0,
                support_usd=0.0,
                marketplace_usd=0.0,
                refunds_usd=0.0,
                other_adjustments_usd=0.0,
                net_due_usd=2.0,
                source_kind=SOURCE_KIND_DATA_EXPORT,
            )
        )
        session.commit()

        payload = build_billing_overview_response(session, connection.id)

    assert payload["daily_net_due"][0]["date"] == month_start.isoformat()
    assert payload["daily_net_due"][-1]["date"] == today.isoformat()
