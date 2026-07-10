from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.pool import NullPool
from typing import Generator
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


def build_engine(database_url: str | None = None, **kwargs):
    url = database_url or settings.database_url
    engine_kwargs = dict(
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        pool_pre_ping=True,
        echo=settings.debug,
    )
    engine_kwargs.update(kwargs)
    return create_engine(url, **engine_kwargs)


engine = build_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a database session per request."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all_tables() -> None:
    """Create all tables defined in models (used for testing / dev bootstrap)."""
    # Import all models so Base.metadata is populated before create_all
    from app.models import user, lead, campaign, campaign_event, email_account, crm_connection  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("All database tables created.")


def drop_all_tables() -> None:
    """Drop all tables (used for testing teardown)."""
    Base.metadata.drop_all(bind=engine)
    logger.warning("All database tables dropped.")
