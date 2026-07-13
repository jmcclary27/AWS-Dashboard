from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app import main
from app.db import readiness


def make_alembic_engine(revision: str | None = None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    if revision is not None:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            connection.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": revision})
    return engine


def test_healthcheck_is_dependency_free(monkeypatch) -> None:
    monkeypatch.setattr(main, "database_is_ready", lambda: False)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_ready_when_database_matches_head(monkeypatch) -> None:
    monkeypatch.setattr(main, "database_is_ready", lambda: True)

    with TestClient(main.app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_returns_safe_503_when_database_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(main, "database_is_ready", lambda: False)

    with TestClient(main.app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready."}


def test_database_is_ready_when_revision_matches_dynamic_head(monkeypatch) -> None:
    engine = make_alembic_engine("0003")
    monkeypatch.setattr(readiness, "get_engine", lambda: engine)
    monkeypatch.setattr(readiness, "get_alembic_head_revision", lambda: "0003")

    assert readiness.database_is_ready() is True


def test_database_is_not_ready_when_database_is_unavailable(monkeypatch) -> None:
    def unavailable_engine():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(readiness, "get_engine", unavailable_engine)
    monkeypatch.setattr(readiness, "get_alembic_head_revision", lambda: "0003")

    assert readiness.database_is_ready() is False


def test_database_is_not_ready_when_revision_is_stale(monkeypatch) -> None:
    engine = make_alembic_engine("0002")
    monkeypatch.setattr(readiness, "get_engine", lambda: engine)
    monkeypatch.setattr(readiness, "get_alembic_head_revision", lambda: "0003")

    assert readiness.database_is_ready() is False


def test_database_is_not_ready_when_alembic_revision_is_missing(monkeypatch) -> None:
    engine = make_alembic_engine()
    monkeypatch.setattr(readiness, "get_engine", lambda: engine)
    monkeypatch.setattr(readiness, "get_alembic_head_revision", lambda: "0003")

    assert readiness.database_is_ready() is False
