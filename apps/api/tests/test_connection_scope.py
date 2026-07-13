from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Connection, ConnectionAccount, DailyAccountCost, DailyTeamCost, Forecast, Team
from app.db.seed import ensure_reference_data, get_unallocated_team_id
from app.db.session import get_db
from app.main import app
from app.services import collectors


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session)


def make_test_client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


class OrgStubClient:
    def __init__(self, fail_tag: bool = False, fail_forecast: bool = False):
        self.fail_tag = fail_tag
        self.fail_forecast = fail_forecast
        self.today = datetime.now(timezone.utc).date()

    def get_cost_and_usage(self, **kwargs):
        group_by = kwargs["GroupBy"]
        if len(group_by) == 2 and group_by[1]["Key"] == "SERVICE":
            return {
                "DimensionValueAttributes": [
                    {"Value": "555555555555", "Attributes": {"description": "Org Prod"}},
                    {"Value": "666666666666", "Attributes": {"description": "Org Data"}},
                ],
                "ResultsByTime": [
                    {
                        "TimePeriod": {"Start": self.today.isoformat(), "End": self.today.isoformat()},
                        "Groups": [
                            {"Keys": ["555555555555", "Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "100.0", "Unit": "USD"}}},
                            {"Keys": ["666666666666", "Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "40.0", "Unit": "USD"}}},
                        ],
                    }
                ],
            }
        if self.fail_tag:
            raise RuntimeError("tag query failed")
        return {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": self.today.isoformat(), "End": self.today.isoformat()},
                    "Groups": [
                        {"Keys": ["555555555555", "Team$Platform"], "Metrics": {"UnblendedCost": {"Amount": "100.0", "Unit": "USD"}}},
                        {"Keys": ["666666666666", "Team$Data"], "Metrics": {"UnblendedCost": {"Amount": "40.0", "Unit": "USD"}}},
                    ],
                }
            ]
        }

    def get_cost_forecast(self, **kwargs):
        if self.fail_forecast:
            raise RuntimeError("forecast unavailable")
        return {
            "ForecastResultsByTime": [
                {
                    "TimePeriod": {
                        "Start": (self.today.replace(day=min(self.today.day + 1, 28))).isoformat(),
                        "End": (self.today.replace(day=min(self.today.day + 2, 28))).isoformat(),
                    },
                    "MeanValue": "12.5",
                }
            ]
        }


class AccountRoleStubClient:
    def __init__(self):
        self.today = datetime.now(timezone.utc).date()

    def get_cost_and_usage(self, **kwargs):
        group_by = kwargs["GroupBy"]
        if group_by[0]["Key"] == "SERVICE":
            return {
                "ResultsByTime": [
                    {
                        "TimePeriod": {"Start": self.today.isoformat(), "End": self.today.isoformat()},
                        "Groups": [
                            {"Keys": ["Amazon RDS"], "Metrics": {"UnblendedCost": {"Amount": "75.0", "Unit": "USD"}}}
                        ],
                    }
                ]
            }
        return {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": self.today.isoformat(), "End": self.today.isoformat()},
                    "Groups": [
                        {"Keys": ["Team$Finance"], "Metrics": {"UnblendedCost": {"Amount": "75.0", "Unit": "USD"}}}
                    ],
                }
            ]
        }

    def get_cost_forecast(self, **kwargs):
        return {
            "ForecastResultsByTime": [
                {
                    "TimePeriod": {
                        "Start": (self.today.replace(day=min(self.today.day + 1, 28))).isoformat(),
                        "End": (self.today.replace(day=min(self.today.day + 2, 28))).isoformat(),
                    },
                    "MeanValue": "9.0",
                }
            ]
        }


def test_connection_scoped_routes_require_an_explicit_connection_id() -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        ensure_reference_data(session)
        session.commit()

    with make_test_client(session_factory) as client:
        response = client.get("/api/v1/summary?range=30d")

    assert response.status_code == 422
    assert "connection_id" in response.text


def test_create_account_role_connection_creates_primary_membership() -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        ensure_reference_data(session)
        session.commit()

    with make_test_client(session_factory) as client:
        me = client.get("/api/v1/me")
        assert me.status_code == 200
        workspace_id = next(item["id"] for item in me.json()["workspaces"] if not item["is_demo"])
        response = client.post(
            "/api/v1/connections",
            json={
                "workspace_id": workspace_id,
                "name": "Standalone Finance",
                "kind": "account_role",
                "enabled": True,
                "role_arn": "arn:aws:iam::777777777777:role/CostRead",
                "team_tag_key": "Team",
                "account": {
                    "display_name": "Finance Prod",
                    "aws_account_id": "777777777777",
                },
            },
        )

    assert response.status_code == 201
    assert response.json()["item"]["workspace_id"] == workspace_id
    assert response.json()["item"]["external_id_configured"] is False
    with session_factory() as session:
        connection = session.execute(select(Connection).where(Connection.name == "Standalone Finance")).scalar_one()
        membership = session.execute(
            select(ConnectionAccount).where(ConnectionAccount.connection_id == connection.id, ConnectionAccount.is_primary.is_(True))
        ).scalar_one()
        assert membership.membership_source == "manual"


def test_org_management_collector_writes_connection_scoped_data_and_forecast_fallback(monkeypatch) -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Org Scope",
            kind="org_management",
            enabled=True,
            team_tag_key="Team",
        )
        session.add(connection)
        session.commit()
        session.refresh(connection)

        monkeypatch.setattr(collectors, "build_cost_explorer_client", lambda connection: OrgStubClient(fail_forecast=True))
        result = collectors.collect_org_management(session, connection, days=2)
        session.commit()

        assert result.status == "success"
        assert session.scalar(select(func.count(DailyAccountCost.id)).where(DailyAccountCost.connection_id == connection.id)) == 2
        assert session.scalar(select(func.count(Forecast.id)).where(Forecast.connection_id == connection.id)) >= 0
        model_versions = session.scalars(select(Forecast.model_version).where(Forecast.connection_id == connection.id)).all()
        assert all(version == "aws-local-fallback-v1" for version in model_versions)


def test_org_management_collector_uses_unallocated_when_tag_query_fails(monkeypatch) -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Org Partial",
            kind="org_management",
            enabled=True,
            team_tag_key="Team",
        )
        session.add(connection)
        session.commit()
        session.refresh(connection)

        monkeypatch.setattr(collectors, "build_cost_explorer_client", lambda connection: OrgStubClient(fail_tag=True))
        result = collectors.collect_org_management(session, connection, days=2)
        session.commit()

        unallocated_team_id = get_unallocated_team_id(session)
        team_ids = session.scalars(select(DailyTeamCost.team_id).where(DailyTeamCost.connection_id == connection.id)).all()
        assert result.status == "partial_success"
        assert team_ids
        assert set(team_ids) == {unallocated_team_id}


def test_account_role_collector_writes_only_primary_account(monkeypatch) -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        account = collectors.upsert_canonical_account(session, "888888888888", "Standalone Prod", "Team")
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Standalone Scope",
            kind="account_role",
            enabled=True,
            role_arn="arn:aws:iam::888888888888:role/CostRead",
            team_tag_key="Team",
        )
        session.add(connection)
        session.flush()
        collectors.ensure_membership(session, connection, account, membership_source="manual", is_primary=True)
        session.commit()
        session.refresh(connection)

        monkeypatch.setattr(collectors, "build_cost_explorer_client", lambda connection: AccountRoleStubClient())
        result = collectors.collect_account_role(session, connection, days=2)
        session.commit()

        assert result.accounts_synced == 1
        account_ids = session.scalars(select(DailyAccountCost.account_id).where(DailyAccountCost.connection_id == connection.id)).all()
        assert account_ids == [account.id]


def test_sync_connection_uses_calendar_aware_default_window(monkeypatch) -> None:
    session_factory = make_session_factory()
    fixed_today = date(2026, 6, 28)

    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        connection = Connection(
            workspace_id=demo_connection.workspace_id,
            name="Default Window",
            kind="org_management",
            enabled=True,
            team_tag_key="Team",
        )
        session.add(connection)
        session.commit()
        session.refresh(connection)

        captured: dict[str, int] = {}

        def fake_collect_org_management(session, connection, days):
            captured["days"] = days
            return collectors.CollectorResult(
                status="success",
                accounts_synced=0,
                records_written=0,
                window_days=days,
            )

        monkeypatch.setattr(collectors, "utc_today", lambda: fixed_today)
        monkeypatch.setattr(collectors, "collect_org_management", fake_collect_org_management)

        result = collectors.sync_connection(session, connection, days=None)

        assert captured["days"] == 32
        assert result.window_days == 32
