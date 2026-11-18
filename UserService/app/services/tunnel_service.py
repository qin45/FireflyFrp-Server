from __future__ import annotations

import json
import random
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import utcnow
from ..models import PortReservation, Tunnel, TunnelSession, User
from ..schemas import TunnelCreateRequest
from ..security import hash_token, new_token
from .frps_api import FrpsAPI

TUNNEL_TYPES = {"tcp", "udp", "http", "https"}


def _toml_str(value: str) -> str:
    # JSON basic strings are valid TOML basic strings.
    return json.dumps(value, ensure_ascii=False)


def build_frpc_config(
    tunnel: Tunnel, token: str, username: str, settings: Settings
) -> str:
    lines = [
        f"serverAddr = {_toml_str(settings.frps.public_host)}",
        f"serverPort = {settings.frps.bind_port}",
    ]
    if settings.frps.auth_token:
        lines.append(f"auth.token = {_toml_str(settings.frps.auth_token)}")
    lines.extend(
        [
            f"user = {_toml_str(username)}",
            f"clientID = {_toml_str(tunnel.id)}",
            f"metadatas.token = {_toml_str(token)}",
            f"metadatas.tunnel_id = {_toml_str(tunnel.id)}",
            "",
            "[[proxies]]",
            f"name = {_toml_str(tunnel.id)}",
            f"type = {_toml_str(tunnel.type)}",
            f"localIP = {_toml_str(tunnel.local_ip)}",
            f"localPort = {tunnel.local_port}",
        ]
    )
    if tunnel.type in ("tcp", "udp"):
        lines.append(f"remotePort = {tunnel.remote_port}")
    else:
        lines.append(f"subdomain = {_toml_str(tunnel.subdomain or tunnel.id)}")
    return "\n".join(lines) + "\n"


def public_address(tunnel: Tunnel, settings: Settings) -> str | None:
    if tunnel.type in ("tcp", "udp"):
        if tunnel.remote_port is None:
            return None
        return f"{settings.frps.public_host}:{tunnel.remote_port}"
    if not tunnel.domain:
        return None
    if tunnel.type == "http":
        port = settings.frps.vhost_http_port
        suffix = "" if port == 80 else f":{port}"
        return f"http://{tunnel.domain}{suffix}"
    if tunnel.type == "https":
        port = settings.frps.vhost_https_port
        suffix = "" if port == 443 else f":{port}"
        return f"https://{tunnel.domain}{suffix}"
    return None


async def _online_ports(frps: FrpsAPI) -> set[int]:
    try:
        return await frps.get_online_remote_ports()
    except Exception as exc:  # noqa: BLE001 - translate to a service error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"frps admin API unavailable: {exc}",
        ) from exc


async def _online_domains(frps: FrpsAPI) -> set[str]:
    try:
        return await frps.get_online_domains()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"frps admin API unavailable: {exc}",
        ) from exc


async def _pick_port(
    db: AsyncSession, settings: Settings, online_ports: set[int]
) -> int:
    reserved = set(
        (
            await db.scalars(
                select(PortReservation.remote_port).where(
                    PortReservation.remote_port.between(
                        settings.limits.port_range_start,
                        settings.limits.port_range_end,
                    )
                )
            )
        ).all()
    )
    # Also exclude ports held by existing tunnel rows. This matters for data
    # created by older versions or manual inserts that do not have a matching
    # port_reservations row; the unique index on tunnels.remote_port would
    # otherwise reject the insert and force a retry.
    tunnel_ports = set(
        (
            await db.scalars(
                select(Tunnel.remote_port).where(
                    Tunnel.remote_port.is_not(None),
                    Tunnel.remote_port.between(
                        settings.limits.port_range_start,
                        settings.limits.port_range_end,
                    ),
                )
            )
        ).all()
    )
    used = reserved | tunnel_ports
    candidates = [
        port
        for port in range(
            settings.limits.port_range_start, settings.limits.port_range_end + 1
        )
        if port not in used and port not in online_ports
    ]
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no free remote port in configured range",
        )
    return random.choice(candidates)


async def create_tunnel(
    db: AsyncSession,
    settings: Settings,
    frps: FrpsAPI,
    user: User,
    request: TunnelCreateRequest,
) -> tuple[Tunnel, str, str]:
    if request.type not in TUNNEL_TYPES:
        raise HTTPException(status_code=400, detail="invalid tunnel type")
    if request.type == "http" and not settings.limits.enable_http_tunnels:
        raise HTTPException(
            status_code=400, detail="HTTP tunnels are disabled on this node"
        )
    if request.type == "https" and not settings.limits.enable_https_tunnels:
        raise HTTPException(
            status_code=400, detail="HTTPS tunnels are disabled on this node"
        )

    # Capture scalar fields before any rollback. SQLAlchemy expires loaded ORM
    # objects on rollback, and touching user.id afterwards would attempt lazy
    # IO outside the async greenlet (MissingGreenlet).
    user_id = user.id
    username = user.username

    count = await db.scalar(
        select(func.count())
        .select_from(Tunnel)
        .where(Tunnel.user_id == user_id, Tunnel.status != "deleted")
    )
    if (count or 0) >= settings.limits.max_tunnels_per_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"at most {settings.limits.max_tunnels_per_user} tunnels per user",
        )

    online_ports = await _online_ports(frps) if request.type in ("tcp", "udp") else set()
    online_domains = (
        await _online_domains(frps) if request.type in ("http", "https") else set()
    )

    last_error: Exception | None = None
    for _ in range(8):
        tunnel_id = uuid.uuid4().hex
        token = new_token()
        remote_port: int | None = None
        subdomain: str | None = None
        domain: str | None = None

        if request.type in ("tcp", "udp"):
            remote_port = await _pick_port(db, settings, online_ports)
        else:
            subdomain = tunnel_id
            domain = f"{tunnel_id}.{settings.frps.subdomain_host}".lower()
            if domain in online_domains:
                continue
            exists = await db.scalar(
                select(Tunnel.id).where(
                    or_(Tunnel.subdomain == subdomain, Tunnel.domain == domain),
                    Tunnel.status != "deleted",
                )
            )
            if exists:
                continue

        tunnel = Tunnel(
            id=tunnel_id,
            user_id=user_id,
            name=request.name,
            type=request.type,
            local_ip=request.local_ip,
            local_port=request.local_port,
            remote_port=remote_port,
            subdomain=subdomain,
            domain=domain,
            token_hash=hash_token(token),
            status="inactive",
        )
        db.add(tunnel)
        if remote_port is not None:
            db.add(PortReservation(remote_port=remote_port, tunnel_id=tunnel_id))
        try:
            await db.commit()
            await db.refresh(tunnel)
            return tunnel, token, build_frpc_config(tunnel, token, username, settings)
        except IntegrityError as exc:
            last_error = exc
            await db.rollback()
            continue

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"could not allocate tunnel resource: {last_error}",
    )


async def delete_tunnel(
    db: AsyncSession,
    frps: FrpsAPI,
    user: User,
    tunnel_id: str,
) -> None:
    tunnel = await db.scalar(
        select(Tunnel).where(
            Tunnel.id == tunnel_id,
            Tunnel.user_id == user.id,
            Tunnel.status != "deleted",
        )
    )
    if tunnel is None:
        raise HTTPException(status_code=404, detail="tunnel not found")

    sessions = (
        await db.scalars(
            select(TunnelSession).where(
                TunnelSession.tunnel_id == tunnel.id,
                TunnelSession.status.in_(["active", "closing"]),
            )
        )
    ).all()
    for session in sessions:
        client_key = f"{user.username}.{session.client_id or tunnel.id}"
        try:
            await frps.kick_client(client_key)
        except Exception:  # noqa: BLE001 - deletion should still proceed
            pass
        session.status = "ended"
        session.ended_at = utcnow()

    await db.execute(
        delete(PortReservation).where(PortReservation.tunnel_id == tunnel.id)
    )
    # Release unique resources so ports/domains can be reused.
    tunnel.remote_port = None
    tunnel.subdomain = None
    tunnel.domain = None
    tunnel.status = "deleted"
    tunnel.deleted_at = utcnow()
    await db.commit()


async def rotate_token(
    db: AsyncSession,
    settings: Settings,
    frps: FrpsAPI,
    user: User,
    tunnel_id: str,
) -> tuple[Tunnel, str, str]:
    tunnel = await db.scalar(
        select(Tunnel).where(
            Tunnel.id == tunnel_id,
            Tunnel.user_id == user.id,
            Tunnel.status != "deleted",
        )
    )
    if tunnel is None:
        raise HTTPException(status_code=404, detail="tunnel not found")

    sessions = (
        await db.scalars(
            select(TunnelSession).where(
                TunnelSession.tunnel_id == tunnel.id,
                TunnelSession.status.in_(["active", "closing"]),
            )
        )
    ).all()
    for session in sessions:
        try:
            await frps.kick_client(f"{user.username}.{session.client_id or tunnel.id}")
        except Exception:  # noqa: BLE001
            pass
        session.status = "ended"
        session.ended_at = utcnow()
    tunnel.status = "inactive"

    token = new_token()
    tunnel.token_hash = hash_token(token)
    await db.commit()
    await db.refresh(tunnel)
    return tunnel, token, build_frpc_config(tunnel, token, user.username, settings)


async def tunnel_public(
    db: AsyncSession, tunnel: Tunnel, settings: Settings
) -> dict:
    traffic = (
        await db.execute(
            select(
                func.coalesce(func.sum(TunnelSession.traffic_in_bytes), 0),
                func.coalesce(func.sum(TunnelSession.traffic_out_bytes), 0),
            ).where(TunnelSession.tunnel_id == tunnel.id)
        )
    ).one()
    active = bool(
        await db.scalar(
            select(TunnelSession.id).where(
                TunnelSession.tunnel_id == tunnel.id,
                TunnelSession.status == "active",
            )
        )
    )
    return {
        "id": tunnel.id,
        "name": tunnel.name,
        "type": tunnel.type,
        "local_ip": tunnel.local_ip,
        "local_port": tunnel.local_port,
        "remote_port": tunnel.remote_port,
        "subdomain": tunnel.subdomain,
        "domain": tunnel.domain,
        "public_address": public_address(tunnel, settings),
        "status": tunnel.status,
        "active": active,
        "traffic_in_bytes": int(traffic[0] or 0),
        "traffic_out_bytes": int(traffic[1] or 0),
        "created_at": tunnel.created_at,
    }
