"""FastAPI dependencies shared across routes.

Authentication:
  - When AUTH_ENABLED=true (production): validates a signed HS256 JWT from the
    `Authorization: Bearer <token>` header.  The token must carry `{"sub": "<user_id>"}`.
  - When AUTH_ENABLED=false (development default): falls back to the seeded dev
    user so local development works without a login flow.

To generate a suitable SECRET_KEY:
    python -c "import secrets; print(secrets.token_hex(32))"

To replace with a different auth scheme (e.g. OAuth2, third-party IdP):
    1. Change the body of `get_current_user_id` — no route files need updating.
    2. Keep the function signature and return type (int) identical.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from taskorbit.config import get_settings
from taskorbit.database import get_session
from taskorbit.database.crud import get_user, get_user_by_email
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

_DEV_USER_EMAIL = "dev@taskorbit.local"


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> int:
    """Return the authenticated user's ID.

    In production (AUTH_ENABLED=true) validates the JWT Bearer token.
    In development (AUTH_ENABLED=false) returns the seeded dev user.
    """
    settings = get_settings()

    if settings.auth_enabled:
        if credentials is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not settings.secret_key:
            logger.error("auth_misconfigured_missing_secret_key")
            raise HTTPException(status_code=500, detail="Server authentication is misconfigured")
        try:
            payload = jwt.decode(
                credentials.credentials,
                settings.secret_key,
                algorithms=["HS256"],
            )
            user_id: int = int(payload["sub"])
        except (JWTError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        user = await get_user(db, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        return user_id

    # Development fallback — disabled in production via AUTH_ENABLED=true
    user = await get_user_by_email(db, _DEV_USER_EMAIL)
    if not user or not user.is_active:
        logger.warning("dev_user_not_found_or_inactive", email=_DEV_USER_EMAIL)
        raise HTTPException(
            status_code=401,
            detail="Dev user not found — run: poetry run python scripts/seed_defaults.py",
        )
    return user.id
