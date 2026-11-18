from __future__ import annotations

import uuid

from sqlalchemy import select

from app import db as db_module
from app.models import PortReservation, Tunnel, User
from app.schemas import TunnelCreateRequest
from app.services import tunnel_service
from tests.helpers import register


async def test_create_tunnel_survives_integrity_retry(client, app, monkeypatch):
    await register(client, "alice")

    existing_id = uuid.uuid4().hex
    async with db_module.SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "alice"))
        assert user is not None
        db.add(
            Tunnel(
                id=existing_id,
                user_id=user.id,
                name="existing",
                type="tcp",
                local_ip="127.0.0.1",
                local_port=22,
                remote_port=20000,
                token_hash="0" * 64,
                status="inactive",
            )
        )
        db.add(PortReservation(remote_port=20000, tunnel_id=existing_id))
        await db.commit()

    calls = 0

    async def pick_port(_db, _settings, _online_ports):
        nonlocal calls
        calls += 1
        return 20000 if calls == 1 else 20001

    monkeypatch.setattr(tunnel_service, "_pick_port", pick_port)

    async with db_module.SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "alice"))
        assert user is not None
        user_id = user.id
        tunnel, _token, _config = await tunnel_service.create_tunnel(
            db,
            app.state.settings,
            app.state.frps,
            user,
            TunnelCreateRequest(
                type="tcp",
                name="retry",
                local_ip="127.0.0.1",
                local_port=22,
            ),
        )
        assert tunnel.remote_port == 20001
        assert tunnel.user_id == user_id

    assert calls == 2
