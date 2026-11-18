from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_db, utcnow
from ..deps import get_current_session, get_settings
from ..models import User, UserSession
from ..schemas import (
    AuthResponse,
    LoginRequest,
    PasswordChangeRequest,
    RegisterRequest,
    UserPublic,
)
from ..security import hash_password, hash_token, new_token, verify_password
from ..serializers import user_public

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    existing = await db.scalar(select(User.id).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="username already exists")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        traffic_quota_bytes=settings.limits.default_traffic_quota_bytes,
        traffic_used_bytes=0,
        rate_limit_mbps=settings.limits.default_rate_limit_mbps,
        status="active",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user_public(user)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = await db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")
    if user.status == "disabled":
        raise HTTPException(status_code=403, detail="user is disabled")

    token = new_token()
    expires_at = utcnow() + timedelta(hours=settings.server.session_ttl_hours)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires_at,
        )
    )
    await db.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": user_public(user),
    }


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChangeRequest,
    current: tuple[UserSession, User] = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _session, user = current
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="old password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current: tuple[UserSession, User] = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    session, _user = current
    await db.delete(session)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
