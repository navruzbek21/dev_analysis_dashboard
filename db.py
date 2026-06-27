import logging
from contextlib import contextmanager

from config import settings


logger = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine, text
except ImportError:  # pragma: no cover - exercised only in incomplete local envs
    create_engine = None
    text = None


def _create_engine_once():
    if not settings.database_url:
        return None
    if create_engine is None:
        raise RuntimeError("SQLAlchemy is required for DATA_SOURCE=sql")

    common = dict(pool_pre_ping=True, future=True)
    if settings.database_url.startswith("sqlite"):
        return create_engine(settings.database_url, **common)

    common.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
    )
    return create_engine(settings.database_url, **common)


engine = _create_engine_once()


def get_engine():
    if engine is None:
        raise RuntimeError("SQL engine is not configured. Set DATABASE_URL or use DATA_SOURCE=parquet.")
    return engine


@contextmanager
def connection_scope():
    with get_engine().connect() as connection:
        yield connection


def check_database_connection():
    if text is None:
        return False
    try:
        with connection_scope() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database readiness check failed")
        return False
