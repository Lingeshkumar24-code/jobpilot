"""
Registration, login, logout and "who am I".

The browser gets an httpOnly session cookie; API clients can keep using the
returned bearer token. Both are signed with the same short-lived JWT.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limit_auth
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.core import AuditLog, CandidateProfile, User, UserPreference
from app.schemas.auth import Token, UserCreate, UserLogin, UserOut
from app.services import audit

router = APIRouter()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_auth)],
)
async def register(
    payload: UserCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    email = payload.email.strip().lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    user = User(email=email, hashed_password=hash_password(payload.password))
    db.add(user)
    await db.flush()

    # Every user gets an empty profile and preference row. Nothing is guessed.
    db.add(CandidateProfile(user_id=user.id, email=email))
    db.add(UserPreference(user_id=user.id, preferences={}))
    await audit.record(
        db,
        user_id=user.id,
        action="auth.registered",
        resource_type="user",
        resource_id=user.id,
        request=request,
    )

    token = create_access_token(subject=str(user.id))
    set_session_cookie(response, token)
    await db.commit()
    await db.refresh(user)
    return UserOut(id=str(user.id), email=user.email, is_active=user.is_active, full_name=user.full_name)


@router.post("/login", response_model=Token, dependencies=[Depends(limit_auth)])
async def login(
    payload: UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    email = payload.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        # Same message for unknown user and wrong password: no account probing.
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    user.last_login_at = datetime.now(timezone.utc)
    await audit.record(
        db,
        user_id=user.id,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        request=request,
    )
    await db.commit()

    token = create_access_token(subject=str(user.id))
    set_session_cookie(response, token)
    return Token(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
):
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=str(current_user.id),
        email=current_user.email,
        is_active=current_user.is_active,
        full_name=current_user.full_name,
    )


@router.get("/sessions", response_model=list[dict])
async def recent_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent security events for the signed-in account (no secrets)."""
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == current_user.id, AuditLog.action.like("auth.%"))
            .order_by(AuditLog.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return [
        {
            "action": row.action,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "created_at": row.created_at,
        }
        for row in rows
    ]
