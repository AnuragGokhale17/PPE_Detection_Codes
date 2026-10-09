from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.sqlalchemy_url
    if str(url).startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # inference.py already holds up to 20 connections; keep the API's share modest
    return create_engine(url, pool_size=10, max_overflow=10, pool_pre_ping=True, pool_recycle=1800)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
