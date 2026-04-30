"""PostgreSQL access layer.

Provides the async SQLAlchemy engine and session factory. Use
`get_session()` as a FastAPI dependency to obtain an `AsyncSession`
that is automatically closed after the request.

Usage:
    from taskorbit.database import get_session
    from sqlalchemy.ext.asyncio import AsyncSession

    async def my_endpoint(session: AsyncSession = Depends(get_session)):
        ...
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from taskorbit.config import get_settings

_settings = get_settings()

# Convert postgresql:// → postgresql+psycopg:// for the async driver.
_db_url = _settings.database_url.replace(
    "postgresql://", "postgresql+psycopg://", 1
)

engine = create_async_engine(
    _db_url,
    echo=_settings.is_development,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an AsyncSession, closes it on exit."""
    async with AsyncSessionLocal() as session:
        yield session
