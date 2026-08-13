from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
