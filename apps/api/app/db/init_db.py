from pathlib import Path
from datetime import date

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select

from app.config import get_settings
from app.db.models import DailyAccountCost, DailyBillingTotal
from app.db.seed import ensure_reference_data, reset_demo_dataset
from app.db.session import get_session_local
from app.services.billing import build_demo_billing_truth


BASELINE_REVISION = "0001_baseline"


def get_alembic_head_revision(database_url: str | None = None) -> str | None:
    """Return the current Alembic head from the migration scripts.

    Deriving this from the script directory keeps migration checks correct when
    a new revision is added, rather than coupling runtime behavior to a
    hard-coded revision identifier.
    """
    config = build_alembic_config(database_url or get_settings().database_url)
    return ScriptDirectory.from_config(config).get_current_head()


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
        return get_alembic_head_revision(database_url)
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
        demo_connection, _, _ = ensure_reference_data(session)
        has_costs = session.scalar(select(DailyAccountCost.id).limit(1))
        if not has_costs:
            reset_demo_dataset(session, days=settings.seed_days)
        else:
            has_billing = session.scalar(select(DailyBillingTotal.id).limit(1))
            if not has_billing:
                build_demo_billing_truth(session, demo_connection, date.today())
            session.commit()


if __name__ == "__main__":
    main()
