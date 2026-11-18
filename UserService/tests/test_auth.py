from __future__ import annotations

from tests.helpers import auth, login, register


async def test_register_login_and_default_quota(client):
    user = await register(client)
    assert user["username"] == "alice"
    assert user["traffic_quota_bytes"] == 0
    assert user["traffic_remaining_bytes"] == 0
    assert user["rate_limit_mbps"] == 10

    token = await login(client)
    response = await client.get("/api/v1/user", headers=auth(token))
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "alice"
    assert data["traffic_remaining_bytes"] == 0
    assert data["max_tunnels"] == 10
    assert data["max_active_tunnels"] == 3


async def test_duplicate_username_and_wrong_password(client):
    await register(client)
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "password123"},
    )
    assert response.status_code == 409

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )
    assert response.status_code == 401


async def test_change_password_revokes_sessions(client):
    await register(client)
    token = await login(client)

    response = await client.post(
        "/api/v1/auth/password",
        json={"old_password": "password123", "new_password": "newpassword123"},
        headers=auth(token),
    )
    assert response.status_code == 204

    response = await client.get("/api/v1/user", headers=auth(token))
    assert response.status_code == 401

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password123"},
    )
    assert response.status_code == 401

    await login(client, password="newpassword123")


async def test_password_validation(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": "ab", "password": "short"},
    )
    assert response.status_code == 422
