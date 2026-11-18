from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_db
from ..deps import get_current_user, get_settings
from ..models import Tunnel, User
from ..schemas import TunnelCreateRequest, TunnelCreateResponse, TunnelTokenResponse
from ..services import tunnel_service

router = APIRouter(prefix="/api/v1/tunnels", tags=["tunnels"])


@router.get("")
async def list_tunnels(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    tunnels = (
        await db.scalars(
            select(Tunnel)
            .where(Tunnel.user_id == user.id, Tunnel.status != "deleted")
            .order_by(Tunnel.created_at.asc())
        )
    ).all()
    return [await tunnel_service.tunnel_public(db, tunnel, settings) for tunnel in tunnels]


@router.post("", response_model=TunnelCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tunnel(
    payload: TunnelCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    tunnel, token, frpc_config = await tunnel_service.create_tunnel(
        db, settings, request.app.state.frps, user, payload
    )
    return {
        "tunnel": await tunnel_service.tunnel_public(db, tunnel, settings),
        "token": token,
        "frpc_config": frpc_config,
    }


@router.delete("/{tunnel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tunnel(
    tunnel_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await tunnel_service.delete_tunnel(db, request.app.state.frps, user, tunnel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{tunnel_id}/token", response_model=TunnelTokenResponse)
async def rotate_tunnel_token(
    tunnel_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    _tunnel, token, frpc_config = await tunnel_service.rotate_token(
        db, settings, request.app.state.frps, user, tunnel_id
    )
    return {"token": token, "frpc_config": frpc_config}


@router.get("/{tunnel_id}")
async def get_tunnel(
    tunnel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    tunnel = await db.scalar(
        select(Tunnel).where(
            Tunnel.id == tunnel_id,
            Tunnel.user_id == user.id,
            Tunnel.status != "deleted",
        )
    )
    if tunnel is None:
        raise HTTPException(status_code=404, detail="tunnel not found")
    return await tunnel_service.tunnel_public(db, tunnel, settings)
