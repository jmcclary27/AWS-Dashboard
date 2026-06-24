from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

from app.config import get_settings
from app.db.models import DailyAccountCost
from app.db.seed import ensure_reference_data, reset_demo_dataset
from app.db.session import get_session_local


BASELINE_REVISION = "0001_baseline"
HEAD_REVISION = "0002_connection_scope"


def legacy_schema_revision(database_url: str) -> str | None:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
    finally:
        engine.dispose()

    if "alembic_version" in table_names:
        return None
    if "connections" in table_names and "connection_accounts" in table_names:
        return HEAD_REVISION
    if "accounts" in table_names:
        return BASELINE_REVISION
    return None


def build_alembic_config(database_url: str) -> Config:
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(alembic_ini.parent / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations() -> None:
    database_url = get_settings().database_url
    config = build_alembic_config(database_url)
    stamped_revision = legacy_schema_revision(database_url)
    if stamped_revision:
        command.stamp(config, stamped_revision)
    command.upgrade(config, "head")


def main() -> None:
    settings = get_settings()
    run_migrations()

    with get_session_local()() as session:
        ensure_reference_data(session)
        has_costs = session.scalar(select(DailyAccountCost.id).limit(1))
        if not has_costs:
            reset_demo_dataset(session, days=settings.seed_days)
        else:
            session.commit()


if __name__ == "__main__":
    main()
