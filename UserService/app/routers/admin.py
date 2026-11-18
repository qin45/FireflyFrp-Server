from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import require_admin
from ..models import Tunnel, User, UserSession
from ..schemas import AdminUserPatch
from ..security import hash_password, rate_limit_bytes_per_second
from ..serializers import user_public
from ..services.billing import kick_user_sessions
from ..services.tunnel_service import tunnel_public

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/users")
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(User.username.like(pattern))
        count_stmt = count_stmt.where(User.username.like(pattern))
    total = int(await db.scalar(count_stmt) or 0)
    users = (
        await db.scalars(
            stmt.order_by(User.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [user_public(user) for user in users],
    }


@router.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user_public(user)


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    payload: AdminUserPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    if payload.remaining_traffic_bytes is not None:
        user.traffic_quota_bytes = (
            user.traffic_used_bytes + payload.remaining_traffic_bytes
        )
        if payload.remaining_traffic_bytes > 0 and user.status == "exhausted":
            user.status = "active"
    if payload.traffic_quota_bytes is not None:
        user.traffic_quota_bytes = payload.traffic_quota_bytes
        if user.traffic_quota_bytes > user.traffic_used_bytes and user.status == "exhausted":
            user.status = "active"

    if payload.rate_limit_mbps is not None:
        user.rate_limit_mbps = payload.rate_limit_mbps
        try:
            await request.app.state.frps.set_user_bandwidth(
                user.username,
                rate_limit_bytes_per_second(payload.rate_limit_mbps),
            )
        except Exception:  # noqa: BLE001 - DB update still succeeds
            logger.warning("failed to apply bandwidth to frps", exc_info=True)

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        await db.execute(delete(UserSession).where(UserSession.user_id == user.id))

    if payload.status is not None:
        user.status = payload.status
        if payload.status == "disabled":
            await kick_user_sessions(
                _session_factory(db), request.app.state.frps, user.id
            )

    await db.commit()
    await db.refresh(user)
    return user_public(user)


@router.post("/users/{user_id}/kick")
async def kick_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    keys = await kick_user_sessions(_session_factory(db), request.app.state.frps, user.id)
    return {"user": user.username, "kicked": len(keys), "keys": keys}


@router.get("/tunnels")
async def list_tunnels(
    request: Request,
    user_id: int = Query(ge=1),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    tunnels = (
        await db.scalars(
            select(Tunnel)
            .where(Tunnel.user_id == user_id, Tunnel.status != "deleted")
            .order_by(Tunnel.created_at.asc())
        )
    ).all()
    return [
        await tunnel_public(db, tunnel, request.app.state.settings)
        for tunnel in tunnels
    ]


def _session_factory(db: AsyncSession):
    # kick_user_sessions expects a session factory; reuse the same engine.
    from .. import db as db_module

    if db_module.SessionLocal is None:
        raise RuntimeError("database is not initialized")
    return db_module.SessionLocal
