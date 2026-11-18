from __future__ import annotations

import hmac
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import with_for_update
from ..models import Tunnel, TunnelSession, User
from ..security import format_frp_bandwidth, hash_token


class PluginReject(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _reject(reason: str) -> None:
    raise PluginReject(reason)


def _ensure_user_active(user: User) -> None:
    if user.status == "disabled":
        _reject("user is disabled")
    if user.status == "exhausted":
        _reject("traffic exhausted")
    if user.traffic_quota_bytes <= 0 or user.traffic_used_bytes >= user.traffic_quota_bytes:
        _reject("traffic exhausted")


def _check_token(tunnel: Tunnel, token: str) -> None:
    if not token:
        _reject("missing tunnel token")
    if not hmac.compare_digest(tunnel.token_hash, hash_token(token)):
        _reject("invalid tunnel token")


async def _query_user_tunnel(
    db: AsyncSession, username: str, tunnel_id: str, token: str
) -> tuple[User, Tunnel]:
    if not username:
        _reject("missing user")
    if not tunnel_id:
        _reject("missing tunnel id")
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        _reject("unknown user")
    tunnel = await db.scalar(
        select(Tunnel).where(
            Tunnel.id == tunnel_id,
            Tunnel.user_id == user.id,
            Tunnel.status != "deleted",
        )
    )
    if tunnel is None:
        _reject("unknown tunnel")
    _check_token(tunnel, token)
    return user, tunnel


async def _active_tunnel_count(
    db: AsyncSession, user_id: int, exclude_tunnel_id: str
) -> int:
    count = await db.scalar(
        select(func.count(func.distinct(TunnelSession.tunnel_id))).where(
            TunnelSession.user_id == user_id,
            TunnelSession.status == "active",
            TunnelSession.tunnel_id != exclude_tunnel_id,
        )
    )
    return int(count or 0)


def _ensure_tunnel_type_enabled(settings: Settings, tunnel: Tunnel) -> None:
    if tunnel.type == "http" and not settings.limits.enable_http_tunnels:
        _reject("HTTP tunnels are disabled on this node")
    if tunnel.type == "https" and not settings.limits.enable_https_tunnels:
        _reject("HTTPS tunnels are disabled on this node")


def _validate_proxy(user: User, tunnel: Tunnel, content: dict[str, Any]) -> str:
    proxy_type = str(content.get("proxy_type") or "")
    if proxy_type != tunnel.type:
        _reject("proxy type does not match tunnel type")

    proxy_name = str(content.get("proxy_name") or "")
    allowed_names = {tunnel.id, f"{user.username}.{tunnel.id}"}
    if proxy_name not in allowed_names:
        _reject("proxy name does not match tunnel id")

    if tunnel.type in ("tcp", "udp"):
        try:
            remote_port = int(content.get("remote_port") or 0)
        except (TypeError, ValueError):
            _reject("invalid remote port")
        if remote_port != tunnel.remote_port:
            _reject("remote port does not match tunnel")
    else:
        subdomain = str(content.get("subdomain") or "")
        custom_domains = content.get("custom_domains") or []
        domains = {str(item).lower() for item in custom_domains}
        if subdomain != tunnel.subdomain and (tunnel.domain or "") not in domains:
            _reject("domain does not match tunnel")
    return proxy_name


async def handle(
    db: AsyncSession, settings: Settings, op: str, content: dict[str, Any]
) -> dict[str, Any]:
    if op == "Login":
        await login(db, settings, content)
        return {"reject": False, "unchange": True}
    if op == "NewProxy":
        modified = await new_proxy(db, settings, content)
        return {"reject": False, "unchange": False, "content": modified}
    if op == "Ping":
        await ping(db, settings, content)
        return {"reject": False, "unchange": True}
    if op == "NewUserConn":
        await new_user_conn(db, settings, content)
        return {"reject": False, "unchange": True}
    if op == "CloseProxy":
        await close_proxy(db, settings, content)
        return {"reject": False, "unchange": True}
    _reject(f"unsupported op: {op}")
    return {}


async def login(db: AsyncSession, settings: Settings, content: dict[str, Any]) -> None:
    username = str(content.get("user") or "")
    metas = content.get("metas") or {}
    tunnel_id = str(content.get("client_id") or metas.get("tunnel_id") or "")
    token = str(metas.get("token") or "")
    user, tunnel = await _query_user_tunnel(db, username, tunnel_id, token)
    _ensure_tunnel_type_enabled(settings, tunnel)
    _ensure_user_active(user)
    active = await _active_tunnel_count(db, user.id, tunnel.id)
    if active >= settings.limits.max_active_tunnels:
        _reject(f"at most {settings.limits.max_active_tunnels} active tunnels")


async def new_proxy(
    db: AsyncSession, settings: Settings, content: dict[str, Any]
) -> dict[str, Any]:
    user_info = content.get("user") or {}
    username = str(user_info.get("user") or "")
    metas = user_info.get("metas") or {}
    tunnel_id = str(metas.get("tunnel_id") or "")
    token = str(metas.get("token") or "")
    run_id = str(user_info.get("run_id") or "")

    user, tunnel = await _query_user_tunnel(db, username, tunnel_id, token)
    _ensure_tunnel_type_enabled(settings, tunnel)
    _ensure_user_active(user)
    proxy_name = _validate_proxy(user, tunnel, content)

    # Serialize session activation per user on MySQL.
    locked_user = await db.scalar(
        with_for_update(select(User).where(User.id == user.id), db)
    )
    if locked_user is None:
        _reject("unknown user")
    _ensure_user_active(locked_user)

    active = await _active_tunnel_count(db, user.id, tunnel.id)
    if active >= settings.limits.max_active_tunnels:
        _reject(f"at most {settings.limits.max_active_tunnels} active tunnels")

    sessions = (
        await db.scalars(
            select(TunnelSession).where(
                TunnelSession.tunnel_id == tunnel.id,
                TunnelSession.status == "active",
            )
        )
    ).all()
    same_session: TunnelSession | None = None
    for session in sessions:
        if run_id and session.run_id == run_id:
            same_session = session
        else:
            session.status = "closing"

    if same_session is not None:
        same_session.proxy_name = proxy_name
    else:
        # A brand-new tunnel starts counting from zero, so traffic between
        # proxy registration and the first poll is charged. A reconnect uses
        # None so the poller takes the current counter as its baseline and does
        # not re-bill traffic already counted by an earlier session.
        has_history = await db.scalar(
            select(TunnelSession.id).where(TunnelSession.tunnel_id == tunnel.id).limit(1)
        )
        baseline = 0 if has_history is None else None
        db.add(
            TunnelSession(
                tunnel_id=tunnel.id,
                user_id=user.id,
                run_id=run_id,
                client_id=tunnel.id,
                proxy_name=proxy_name,
                status="active",
                last_today_in=baseline,
                last_today_out=baseline,
            )
        )

    tunnel.status = "active"
    await db.commit()

    # Force the account-level limit and server-side enforcement. Users cannot
    # override this through their own frpc config.
    bandwidth_limit = format_frp_bandwidth(locked_user.rate_limit_mbps)
    content["bandwidth_limit"] = bandwidth_limit
    content["bandwidth_limit_mode"] = "server" if bandwidth_limit else ""
    return content


async def ping(db: AsyncSession, settings: Settings, content: dict[str, Any]) -> None:
    user_info = content.get("user") or {}
    username = str(user_info.get("user") or "")
    if not username:
        _reject("missing user")
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        _reject("unknown user")
    _ensure_user_active(user)


async def new_user_conn(
    db: AsyncSession, settings: Settings, content: dict[str, Any]
) -> None:
    user_info = content.get("user") or {}
    username = str(user_info.get("user") or "")
    if not username:
        _reject("missing user")
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        _reject("unknown user")
    _ensure_user_active(user)


async def close_proxy(
    db: AsyncSession, settings: Settings, content: dict[str, Any]
) -> None:
    user_info = content.get("user") or {}
    username = str(user_info.get("user") or "")
    run_id = str(user_info.get("run_id") or "")
    proxy_name = str(content.get("proxy_name") or "")
    if not username:
        return
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        return

    stmt = select(TunnelSession).where(
        TunnelSession.user_id == user.id,
        TunnelSession.status.in_(["active", "closing"]),
    )
    if run_id:
        stmt = stmt.where(TunnelSession.run_id == run_id)
    if proxy_name:
        stmt = stmt.where(TunnelSession.proxy_name == proxy_name)
    sessions = (await db.scalars(stmt)).all()
    if not sessions:
        return
    for session in sessions:
        session.status = "closing"
    await db.commit()
