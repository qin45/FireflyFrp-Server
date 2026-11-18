from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import get_db, utcnow
from .models import User, UserSession
from .security import constant_time_equals, hash_token


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    token = header[len("Bearer ") :].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    return token


async def get_current_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[UserSession, User]:
    token_hash = hash_token(_bearer_token(request))
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == token_hash)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session"
        )
    session, user = row
    if session.expires_at <= utcnow():
        await db.delete(session)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired"
        )
    if user.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="user is disabled"
        )
    return session, user


async def get_current_user(
    current: tuple[UserSession, User] = Depends(get_current_session),
) -> User:
    return current[1]


async def require_admin(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    token = _bearer_token(request)
    if not settings.server.admin_token or not constant_time_equals(
        token, settings.server.admin_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin token"
        )
