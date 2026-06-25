"""FastAPI dependencies shared across routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from taskorbit.database import get_session
from taskorbit.database.crud import get_user_by_email
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)

_DEV_USER_EMAIL = "dev@taskorbit.local"


async def get_current_user_id(
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> int:
    """Return the authenticated user's ID.

    Auth is not yet implemented — always returns the seeded dev user.
    To add JWT auth: replace this body with token validation; no route
    files need changing.
    """
    user = await get_user_by_email(db, _DEV_USER_EMAIL)
    if not user or not user.is_active:
        logger.warning("dev_user_not_found_or_inactive", email=_DEV_USER_EMAIL)
        raise HTTPException(
            status_code=401,
            detail="Dev user not found — run: poetry run python scripts/seed_defaults.py",
        )
    return user.id
