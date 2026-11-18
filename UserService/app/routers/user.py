from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_db
from ..deps import get_current_user, get_settings
from ..models import Tunnel, User
from ..serializers import user_public
from ..services.tunnel_service import tunnel_public

router = APIRouter(prefix="/api/v1", tags=["user"])


@router.get("/user")
async def user_info(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    tunnels = (
        await db.scalars(
            select(Tunnel)
            .where(Tunnel.user_id == user.id, Tunnel.status != "deleted")
            .order_by(Tunnel.created_at.asc())
        )
    ).all()
    tunnel_items = [await tunnel_public(db, tunnel, settings) for tunnel in tunnels]
    data = user_public(user)
    data.update(
        {
            "max_tunnels": settings.limits.max_tunnels_per_user,
            "max_active_tunnels": settings.limits.max_active_tunnels,
            "enabled_tunnel_types": settings.limits.enabled_tunnel_types(),
            "tunnels": tunnel_items,
        }
    )
    return data
