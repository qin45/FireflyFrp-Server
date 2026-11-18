from __future__ import annotations

from sqlalchemy import select

from app import db as db_module
from app.models import Tunnel, TunnelSession
from app.services.billing import process_once
from tests.helpers import (
    auth,
    create_tunnel,
    grant_traffic,
    login,
    login_content,
    new_proxy_content,
    plugin_call,
    proxy_status,
    register,
)


async def _activate(client, username: str, tunnel: dict, run_id: str = "run-1") -> None:
    result = await plugin_call(
        client, "Login", login_content(username, tunnel, tunnel["token"], run_id)
    )
    assert result["reject"] is False, result
    result = await plugin_call(
        client,
        "NewProxy",
        new_proxy_content(username, tunnel, tunnel["token"], run_id),
    )
    assert result["reject"] is False, result


async def test_billing_delta_and_counter_reset(client, app):
    user = await register(client)
    await grant_traffic(client, user["id"], 10_000_000)
    token = await login(client)
    tunnel = await create_tunnel(client, token, "tcp")
    tunnel_id = tunnel["tunnel"]["id"]
    await _activate(client, "alice", tunnel)

    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    app.state.frps.proxies = [proxy_status("alice", tunnel_id, traffic_in=100, traffic_out=200)]
    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    app.state.frps.proxies = [proxy_status("alice", tunnel_id, traffic_in=300, traffic_out=500)]
    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    response = await client.get("/api/v1/user", headers=auth(token))
    assert response.json()["traffic_used_bytes"] == 800

    # Counter reset (midnight or frps restart): current values are today's new usage.
    app.state.frps.proxies = [proxy_status("alice", tunnel_id, traffic_in=50, traffic_out=60)]
    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    response = await client.get("/api/v1/user", headers=auth(token))
    assert response.json()["traffic_used_bytes"] == 910


async def test_close_one_tunnel_does_not_stop_other_billing(client, app):
    user = await register(client)
    await grant_traffic(client, user["id"], 10_000_000)
    token = await login(client)
    tunnel_a = await create_tunnel(client, token, "tcp", name="a")
    tunnel_b = await create_tunnel(client, token, "tcp", name="b")
    await _activate(client, "alice", tunnel_a, "run-a")
    await _activate(client, "alice", tunnel_b, "run-b")

    id_a = tunnel_a["tunnel"]["id"]
    id_b = tunnel_b["tunnel"]["id"]
    app.state.frps.proxies = [
        proxy_status("alice", id_a, traffic_in=100, traffic_out=100),
        proxy_status("alice", id_b, traffic_in=100, traffic_out=100),
    ]
    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    app.state.frps.proxies = [
        proxy_status("alice", id_a, traffic_in=200, traffic_out=200),
        proxy_status("alice", id_b, traffic_in=200, traffic_out=200),
    ]
    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    await plugin_call(
        client,
        "CloseProxy",
        {
            "user": {
                "user": "alice",
                "metas": {"token": tunnel_a["token"], "tunnel_id": id_a},
                "run_id": "run-a",
            },
            "proxy_name": f"alice.{id_a}",
        },
    )

    app.state.frps.proxies = [
        proxy_status("alice", id_a, traffic_in=300, traffic_out=300),
        proxy_status("alice", id_b, traffic_in=300, traffic_out=300),
    ]
    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    async with db_module.SessionLocal() as session:
        rows = (
            await session.scalars(
                select(TunnelSession).where(TunnelSession.tunnel_id.in_([id_a, id_b]))
            )
        ).all()
        by_tunnel = {row.tunnel_id: row for row in rows}
        assert by_tunnel[id_a].status == "ended"
        assert by_tunnel[id_b].status == "active"

        tunnel_a_row = await session.get(Tunnel, id_a)
        tunnel_b_row = await session.get(Tunnel, id_b)
        assert tunnel_a_row.status == "inactive"
        assert tunnel_b_row.status == "active"

    response = await client.get("/api/v1/user", headers=auth(token))
    assert response.json()["traffic_used_bytes"] == 1200


async def test_quota_exhaustion_triggers_kick(client, app):
    user = await register(client)
    await grant_traffic(client, user["id"], 1000)
    token = await login(client)
    tunnel = await create_tunnel(client, token, "tcp")
    tunnel_id = tunnel["tunnel"]["id"]
    await _activate(client, "alice", tunnel)

    app.state.frps.proxies = [proxy_status("alice", tunnel_id, traffic_in=0, traffic_out=0)]
    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    app.state.frps.proxies = [
        proxy_status("alice", tunnel_id, traffic_in=600, traffic_out=600)
    ]
    await process_once(db_module.SessionLocal, app.state.settings, app.state.frps)

    response = await client.get("/api/v1/user", headers=auth(token))
    assert response.json()["status"] == "exhausted"
    assert f"alice.{tunnel_id}" in app.state.frps.kicks
