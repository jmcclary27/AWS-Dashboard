from pathlib import Path

from alembic import command
import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings
from app.db.init_db import build_alembic_config, get_alembic_head_revision, run_migrations


def test_run_migrations_upgrades_legacy_schema_without_alembic_version(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    database_url = f"sqlite:///{database_path.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    config = build_alembic_config(database_url)
    command.upgrade(config, "0001_baseline")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    engine.dispose()

    run_migrations()

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "connections" in inspector.get_table_names()
        assert "connection_accounts" in inspector.get_table_names()
        forecast_columns = {column["name"] for column in inspector.get_columns("forecasts")}
        assert "connection_id" in forecast_columns

        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert revision == get_alembic_head_revision(database_url)
    finally:
        engine.dispose()
        get_settings.cache_clear()


def _legacy_database_with_non_demo_connection(monkeypatch, tmp_path: Path):
    database_path = tmp_path / "pre-tenancy.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = build_alembic_config(database_url)
    command.upgrade(config, "0003_payable_billing_truth")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO connections (name, kind, enabled, team_tag_key, created_at, updated_at)
                VALUES ('Legacy private', 'org_management', 1, 'Team', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
    engine.dispose()
    return database_url, config


def test_tenancy_migration_refuses_unowned_non_demo_connections(monkeypatch, tmp_path: Path) -> None:
    for variable in (
        "AUTH_BOOTSTRAP_OWNER_SUB",
        "AUTH_BOOTSTRAP_OWNER_EMAIL",
        "AUTH_BOOTSTRAP_OWNER_ISSUER",
        "COGNITO_ISSUER",
    ):
        monkeypatch.delenv(variable, raising=False)
    database_url, config = _legacy_database_with_non_demo_connection(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError, match="non-demo connections without an owner"):
        command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "users" not in inspector.get_table_names()
        assert "workspace_id" not in {column["name"] for column in inspector.get_columns("connections")}
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_tenancy_migration_moves_demo_and_bootstraps_private_connections(monkeypatch, tmp_path: Path) -> None:
    database_url, config = _legacy_database_with_non_demo_connection(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_BOOTSTRAP_OWNER_SUB", "bootstrap-subject")
    monkeypatch.setenv("AUTH_BOOTSTRAP_OWNER_EMAIL", "bootstrap@example.test")
    monkeypatch.setenv("AUTH_BOOTSTRAP_OWNER_ISSUER", "https://issuer.example.test/pool")
    monkeypatch.setenv("AUTH_BOOTSTRAP_WORKSPACE_NAME", "Imported Workspace")

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT c.name, c.created_by_user_id, w.name AS workspace_name, w.is_demo
                    FROM connections AS c
                    JOIN workspaces AS w ON w.id = c.workspace_id
                    ORDER BY c.name
                    """
                )
            ).mappings().all()
            owner = connection.execute(
                text("SELECT id, identity_issuer, subject, email FROM users")
            ).mappings().one()
            membership = connection.execute(
                text("SELECT role FROM workspace_memberships WHERE user_id = :user_id"),
                {"user_id": owner["id"]},
            ).scalar_one()

        by_name = {row["name"]: row for row in rows}
        assert by_name["Local Demo"]["workspace_name"] == "Demo Workspace"
        assert bool(by_name["Local Demo"]["is_demo"]) is True
        assert by_name["Local Demo"]["created_by_user_id"] is None
        assert by_name["Legacy private"]["workspace_name"] == "Imported Workspace"
        assert bool(by_name["Legacy private"]["is_demo"]) is False
        assert by_name["Legacy private"]["created_by_user_id"] == owner["id"]
        assert owner["identity_issuer"] == "https://issuer.example.test/pool"
        assert owner["subject"] == "bootstrap-subject"
        assert owner["email"] == "bootstrap@example.test"
        assert membership == "owner"
    finally:
        engine.dispose()
        get_settings.cache_clear()
