from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()
engine = None
SessionLocal = None


def get_engine():
    global engine
    if engine is None:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
    return engine


def get_session_local():
    global SessionLocal
    if SessionLocal is None:
        SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, class_=Session)
    return SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
