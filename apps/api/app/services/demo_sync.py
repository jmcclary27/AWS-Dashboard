from sqlalchemy.orm import Session

from app.db.seed import refresh_recent_demo_data


def run_demo_sync(session: Session, account_ids: list[int] | None = None, days: int = 14) -> dict[str, int]:
    result = refresh_recent_demo_data(session, account_ids=account_ids, days=days)
    return {
        "status": "success",
        "accounts_synced": result["accounts_synced"],
        "records_written": result["records_written"],
        "window_days": days,
    }

