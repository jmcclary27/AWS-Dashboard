from contextlib import contextmanager

from fastapi.testclient import TestClient
from botocore.exceptions import NoCredentialsError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import Principal, get_current_principal, upsert_principal_user
from app.db.base import Base
from app.db.models import Connection, Workspace
from app.db.seed import ensure_reference_data
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


@contextmanager
def make_test_client(session_factory, principal: Principal | None = None):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_demo_connection_is_read_only_for_validate_and_sync() -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        demo_connection, _, _ = ensure_reference_data(session)
        session.commit()
        demo_connection_id = demo_connection.id

    with make_test_client(session_factory) as client:
        validate = client.post(f"/api/v1/connections/{demo_connection_id}/validate")
        sync = client.post(f"/api/v1/connections/{demo_connection_id}/sync", json={"days": 14})

    assert validate.status_code == 403
    assert sync.status_code == 403


def test_removed_runtime_and_global_mutation_routes_are_not_available() -> None:
    session_factory = make_session_factory()
    with make_test_client(session_factory) as client:
        runtime = client.get("/api/v1/aws/runtime")
        sync_all = client.post("/api/v1/sync/all")
        global_account_write = client.post("/api/v1/accounts", json={})

    assert runtime.status_code == 404
    assert sync_all.status_code == 404
    assert global_account_write.status_code == 405


def test_sync_route_surfaces_sanitized_missing_credentials(monkeypatch) -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        principal = upsert_principal_user(
            session,
            Principal(
                subject="aws-access-owner",
                issuer="tests",
                email="owner@example.test",
                email_verified=True,
                display_name="Owner",
            ),
        )
        workspace = session.execute(
            select(Workspace).where(Workspace.created_by_user_id == principal.user_id, Workspace.is_demo.is_(False))
        ).scalar_one()
        ensure_reference_data(session)
        connection = Connection(
            workspace_id=workspace.id,
            created_by_user_id=principal.user_id,
            name="Org Real",
            kind="org_management",
            enabled=True,
            team_tag_key="Team",
        )
        session.add(connection)
        session.commit()
        connection_id = connection.id

    monkeypatch.setattr(
        collectors,
        "build_cost_explorer_client",
        lambda connection: (_ for _ in ()).throw(NoCredentialsError()),
    )

    with make_test_client(session_factory, principal) as client:
        response = client.post(f"/api/v1/connections/{connection_id}/sync", json={"days": 14})

    assert response.status_code == 400
    assert response.json()["detail"] == "Connection sync failed. Revalidate connection access and retry."
    assert "NoCredentials" not in response.text
