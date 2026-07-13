"""Database readiness checks for the API process."""

from sqlalchemy import text

from app.db.init_db import get_alembic_head_revision
from app.db.session import get_engine


def database_is_ready() -> bool:
    """Return whether Postgres is reachable and upgraded to the migration head.

    Readiness must fail closed: callers receive only a boolean so endpoint
    responses cannot reveal database connection details or migration errors.
    """
    try:
        expected_revision = get_alembic_head_revision()
        if expected_revision is None:
            return False

        with get_engine().connect() as connection:
            current_revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()

        return current_revision == expected_revision
    except Exception:
        # A readiness probe should report a safe 503 for any unavailable or
        # inconsistent database state, including a missing alembic_version table.
        return False
