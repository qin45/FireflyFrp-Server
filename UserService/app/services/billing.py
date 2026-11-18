from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..db import utcnow
from ..models import Tunnel, TunnelSession, User
from .frps_api import FrpsAPI

logger = logging.getLogger(__name__)

OFFLINE_GRACE = timedelta(seconds=15)
STARTUP_GRACE = timedelta(seconds=10)


def _apply_delta(
    session: TunnelSession,
    user: User,
    current_in: int,
    current_out: int,
) -> None:
    last_in = int(session.last_today_in or 0)
    last_out = int(session.last_today_out or 0)
    # A decrease means the daily counter rotated or frps restarted.
    delta_in = current_in - last_in if current_in >= last_in else current_in
    delta_out = current_out - last_out if current_out >= last_out else current_out
    if delta_in > 0:
        session.traffic_in_bytes += delta_in
        user.traffic_used_bytes += delta_in
    if delta_out > 0:
        session.traffic_out_bytes += delta_out
        user.traffic_used_bytes += delta_out
    session.last_today_in = current_in
    session.last_today_out = current_out


async def process_once(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    frps: FrpsAPI,
) -> None:
    proxies = await frps.get_proxies("all")
    proxy_map = {str(proxy.get("name") or ""): proxy for proxy in proxies}

    async with session_factory() as db:
        sessions = (
            await db.scalars(
                select(TunnelSession).where(
                    TunnelSession.status.in_(["active", "closing"])
                )
            )
        ).all()
        if not sessions:
            return

        user_ids = {session.user_id for session in sessions}
        users = {
            user.id: user
            for user in (
                await db.scalars(select(User).where(User.id.in_(user_ids)))
            ).all()
        }
        now = utcnow()
        ended_tunnels: set[str] = set()
        kick_users: set[int] = set()
        changed = False

        for session in sessions:
            user = users.get(session.user_id)
            if user is None:
                session.status = "ended"
                session.ended_at = now
                ended_tunnels.add(session.tunnel_id)
                changed = True
                continue

            proxy = proxy_map.get(session.proxy_name) or proxy_map.get(
                f"{user.username}.{session.tunnel_id}"
            )
            proxy_status = (proxy or {}).get("status") or {}
            phase = str(proxy_status.get("phase") or "offline")
            current_in = int(proxy_status.get("todayTrafficIn") or 0)
            current_out = int(proxy_status.get("todayTrafficOut") or 0)

            if session.status == "closing":
                if proxy is not None and session.last_today_in is not None:
                    _apply_delta(session, user, current_in, current_out)
                session.status = "ended"
                session.ended_at = now
                ended_tunnels.add(session.tunnel_id)
                changed = True
                continue

            if phase != "online":
                if session.last_today_in is None:
                    if now - session.started_at >= STARTUP_GRACE:
                        session.status = "ended"
                        session.ended_at = now
                        ended_tunnels.add(session.tunnel_id)
                        changed = True
                    # Otherwise the proxy may still be registering.
                    continue
                if session.last_sample_at is None:
                    session.last_sample_at = now
                if now - session.last_sample_at < OFFLINE_GRACE:
                    continue
                if proxy is not None:
                    _apply_delta(session, user, current_in, current_out)
                session.status = "ended"
                session.ended_at = now
                ended_tunnels.add(session.tunnel_id)
                changed = True
                continue

            if session.last_today_in is None:
                # Baseline only: traffic before this point belongs to an
                # earlier session or to before the tunnel was started.
                session.last_today_in = current_in
                session.last_today_out = current_out
                session.last_sample_at = now
                changed = True
            else:
                _apply_delta(session, user, current_in, current_out)
                session.last_sample_at = now
                changed = True

            if user.status != "disabled" and (
                user.traffic_quota_bytes <= 0
                or user.traffic_used_bytes >= user.traffic_quota_bytes
            ):
                if user.status != "exhausted":
                    user.status = "exhausted"
                    changed = True
                kick_users.add(user.id)

        # Users may already be exhausted but still have a live session; keep
        # retrying the kick until the session ends.
        exhausted = (
            await db.scalars(select(User).where(User.status == "exhausted"))
        ).all()
        for user in exhausted:
            has_active = await db.scalar(
                select(TunnelSession.id).where(
                    TunnelSession.user_id == user.id,
                    TunnelSession.status == "active",
                )
            )
            if has_active:
                kick_users.add(user.id)

        if changed:
            await db.commit()

        for tunnel_id in ended_tunnels:
            active = await db.scalar(
                select(TunnelSession.id).where(
                    TunnelSession.tunnel_id == tunnel_id,
                    TunnelSession.status == "active",
                )
            )
            if active is None:
                tunnel = await db.get(Tunnel, tunnel_id)
                if tunnel is not None and tunnel.status == "active":
                    tunnel.status = "inactive"
        await db.commit()

    for user_id in kick_users:
        await kick_user_sessions(session_factory, frps, user_id)


async def kick_user_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    frps: FrpsAPI,
    user_id: int,
) -> list[str]:
    async with session_factory() as db:
        user = await db.get(User, user_id)
        if user is None:
            return []
        sessions = (
            await db.scalars(
                select(TunnelSession).where(
                    TunnelSession.user_id == user_id,
                    TunnelSession.status == "active",
                )
            )
        ).all()
        keys = [
            f"{user.username}.{session.client_id or session.tunnel_id}"
            for session in sessions
        ]

    kicked: list[str] = []
    for key in keys:
        try:
            if await frps.kick_client(key):
                kicked.append(key)
        except Exception:  # noqa: BLE001 - best effort, retried next round
            logger.warning("failed to kick frps client %s", key, exc_info=True)
    return kicked


async def billing_loop(settings: Settings, frps: FrpsAPI) -> None:
    from .. import db

    while True:
        try:
            if db.SessionLocal is None:
                await asyncio.sleep(1)
                continue
            await process_once(db.SessionLocal, settings, frps)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - poller must keep running
            logger.exception("billing poll failed")
        await asyncio.sleep(settings.limits.traffic_poll_interval_seconds)
