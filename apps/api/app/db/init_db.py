from sqlalchemy import select

from app.config import get_settings
from app.db.base import Base
from app.db.models import DailyAccountCost
from app.db.seed import ensure_reference_data, reset_demo_dataset
from app.db.session import get_engine, get_session_local


def main() -> None:
    settings = get_settings()
    Base.metadata.create_all(bind=get_engine())

    with get_session_local()() as session:
        ensure_reference_data(session)
        has_costs = session.scalar(select(DailyAccountCost.id).limit(1))
        if not has_costs:
            reset_demo_dataset(session, days=settings.seed_days)
        else:
            session.commit()


if __name__ == "__main__":
    main()
