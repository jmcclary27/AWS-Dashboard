from fastapi.testclient import TestClient
from botocore.exceptions import NoCredentialsError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Connection
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


def make_test_client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_aws_runtime_route_returns_safe_shape(monkeypatch) -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        ensure_reference_data(session)
        session.commit()

    monkeypatch.setattr(
        "app.api.routes.inspect_aws_runtime",
        lambda: {
            "status": "ready",
            "configured": True,
            "identity_verified": True,
            "credential_source": "shared-credentials-file",
            "profile": "default",
            "region": "us-east-1",
            "caller": {
                "account_id": "123456789012",
                "arn": "arn:aws:sts::123456789012:assumed-role/Admin/test",
                "user_id": "AIDATEST",
            },
            "message": "Ambient AWS credentials are available to the API runtime.",
        },
    )

    with make_test_client(session_factory) as client:
        response = client.get("/api/v1/aws/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["credential_source"] == "shared-credentials-file"
    assert payload["caller"]["account_id"] == "123456789012"


def test_validate_demo_connection_returns_ready() -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        ensure_reference_data(session)
        session.commit()

    with make_test_client(session_factory) as client:
        response = client.post("/api/v1/connections/1/validate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["kind"] == "demo"
    assert payload["truth_mode"] == "exact"
    assert payload["checks"][0]["code"] == "demo"


def test_sync_route_surfaces_sanitized_missing_credentials(monkeypatch) -> None:
    session_factory = make_session_factory()
    with session_factory() as session:
        ensure_reference_data(session)
        session.add(Connection(name="Org Real", kind="org_management", enabled=True, team_tag_key="Team"))
        session.commit()

    monkeypatch.setattr(collectors, "build_cost_explorer_client", lambda connection: (_ for _ in ()).throw(NoCredentialsError()))

    with make_test_client(session_factory) as client:
        response = client.post("/api/v1/connections/2/sync", json={"days": 14})

    assert response.status_code == 400
    assert "AWS credentials are not available to the API runtime" in response.json()["detail"]
