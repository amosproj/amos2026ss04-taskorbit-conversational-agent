"""FastAPI dependencies shared across routes.

Auth stub — returns the seeded dev user (id=1) until JWT auth is wired in.

To add real authentication:
  1. Install python-jose + passlib[bcrypt] (or any JWT library).
  2. Replace the body of `get_current_user_id()` with token validation:

     from fastapi.security import OAuth2PasswordBearer
     from jose import jwt, JWTError

     oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")

     async def get_current_user_id(
         token: str = Depends(oauth2_scheme),
         db: AsyncSession = Depends(get_session),
     ) -> int:
         try:
             payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
             user_id: int = int(payload["sub"])
         except (JWTError, KeyError, ValueError):
             raise HTTPException(status_code=401, detail="Invalid or expired token")
         user = await get_user(db, user_id)
         if not user or not user.is_active:
             raise HTTPException(status_code=401, detail="User not found or inactive")
         return user_id

  3. No route file needs to change — they all depend on `get_current_user_id`.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from taskorbit.database import get_session
from taskorbit.database.crud import get_user
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded dev user — swap this entire function for JWT logic when ready.
# ---------------------------------------------------------------------------

_DEV_USER_ID = 1


async def get_current_user_id(
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> int:
    """Return the current user's ID.

    STUB: always returns the seeded dev user (id=1).
    Replace with JWT token validation when auth is implemented.
    """
    user = await get_user(db, _DEV_USER_ID)
    if not user or not user.is_active:
        logger.warning("dev_user_not_found_or_inactive", user_id=_DEV_USER_ID)
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Dev user not found — run seed script first")
    return user.id
