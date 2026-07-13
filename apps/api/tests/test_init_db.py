from pathlib import Path

from alembic import command
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
