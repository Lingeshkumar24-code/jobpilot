from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.core import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    cookie_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    raw_token = token or cookie_token
    if not raw_token:
        raise credentials_error
    request.state.auth_source = "bearer" if token else "cookie"

    user_id = decode_access_token(raw_token)
    if user_id is None:
        raise credentials_error
    try:
        user_uuid = UUID(user_id)
    except (TypeError, ValueError):
        raise credentials_error

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_error
    return user
