from __future__ import annotations

from tests.helpers import (
    ADMIN_HEADERS,
    auth,
    create_tunnel,
    grant_traffic,
    login,
    login_content,
    new_proxy_content,
    plugin_call,
    register,
)


async def test_admin_can_grant_traffic_and_change_rate(client, app):
    user = await register(client)
    await grant_traffic(client, user["id"], 1024 * 1024)

    token = await login(client)
    response = await client.get("/api/v1/user", headers=auth(token))
    assert response.json()["traffic_remaining_bytes"] == 1024 * 1024

    response = await client.patch(
        f"/api/v1/admin/users/{user['id']}",
        json={"rate_limit_mbps": 20},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["rate_limit_mbps"] == 20
    assert app.state.frps.bandwidth == [
        ("alice", 20 * 1_000_000 // 8)
    ]


async def test_admin_can_change_password_and_disable(client):
    user = await register(client)
    old_token = await login(client)

    response = await client.patch(
        f"/api/v1/admin/users/{user['id']}",
        json={"password": "newpassword123"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200

    response = await client.get("/api/v1/user", headers=auth(old_token))
    assert response.status_code == 401

    await login(client, password="newpassword123")

    response = await client.patch(
        f"/api/v1/admin/users/{user['id']}",
        json={"status": "disabled"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "newpassword123"},
    )
    assert response.status_code == 403


async def test_admin_can_list_and_kick(client, app):
    user = await register(client)
    await grant_traffic(client, user["id"], 10_000_000)
    token = await login(client)
    tunnel = await create_tunnel(client, token)

    login_result = await plugin_call(
        client, "Login", login_content("alice", tunnel, tunnel["token"])
    )
    assert login_result["reject"] is False
    proxy_result = await plugin_call(
        client, "NewProxy", new_proxy_content("alice", tunnel, tunnel["token"])
    )
    assert proxy_result["reject"] is False

    response = await client.get("/api/v1/admin/users", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    assert response.json()["total"] == 1

    response = await client.post(
        f"/api/v1/admin/users/{user['id']}/kick", headers=ADMIN_HEADERS
    )
    assert response.status_code == 200
    assert response.json()["kicked"] == 1
    assert app.state.frps.kicks == [f"alice.{tunnel['tunnel']['id']}"]
