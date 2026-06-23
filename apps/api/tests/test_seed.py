from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Account, DailyAccountCost, DailyServiceCost, DailyTeamCost, Forecast, Team
from app.db.seed import ensure_reference_data, reset_demo_dataset


def test_seed_builds_reference_and_cost_data() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, class_=Session)

    with session_factory() as session:
        ensure_reference_data(session)
        reset_demo_dataset(session, days=90)

        account_count = session.scalar(select(func.count(Account.id)))
        team_count = session.scalar(select(func.count(Team.id)))
        daily_account_count = session.scalar(select(func.count(DailyAccountCost.id)))
        daily_service_count = session.scalar(select(func.count(DailyServiceCost.id)))
        daily_team_count = session.scalar(select(func.count(DailyTeamCost.id)))
        forecast_count = session.scalar(select(func.count(Forecast.id)))

        assert account_count >= 4
        assert team_count >= 6
        assert daily_account_count >= 360
        assert daily_service_count > daily_account_count
        assert daily_team_count > daily_account_count
        assert forecast_count >= 0
