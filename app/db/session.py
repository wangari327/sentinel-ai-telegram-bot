from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import sleep

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base
from app.logging import get_logger

logger = get_logger(__name__)

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(*, attempts: int = 12, delay_seconds: float = 2.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError:
            if attempt >= attempts:
                raise
            logger.warning(
                "Database is not ready yet; retrying startup DB init (%s/%s)",
                attempt,
                attempts,
            )
            sleep(delay_seconds)


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
