from __future__ import annotations

from tests.helpers import auth, create_tunnel, login, register


async def test_create_all_tunnel_types(client):
    user = await register(client)
    token = await login(client)

    tcp = await create_tunnel(client, token, "tcp", name="ssh", local_port=22)
    assert 20000 <= tcp["tunnel"]["remote_port"] <= 20010
    assert tcp["tunnel"]["type"] == "tcp"
    assert "remotePort" in tcp["frpc_config"]
    assert "clientID" in tcp["frpc_config"]
    assert "metadatas.token" in tcp["frpc_config"]

    udp = await create_tunnel(client, token, "udp", name="dns", local_port=53)
    assert 20000 <= udp["tunnel"]["remote_port"] <= 20010
    assert udp["tunnel"]["remote_port"] != tcp["tunnel"]["remote_port"]

    http = await create_tunnel(client, token, "http", name="web", local_port=8080)
    assert http["tunnel"]["remote_port"] is None
    assert http["tunnel"]["subdomain"] == http["tunnel"]["id"]
    assert http["tunnel"]["domain"].endswith(".frp.test")
    assert "subdomain" in http["frpc_config"]
    assert "remotePort" not in http["frpc_config"]

    https = await create_tunnel(client, token, "https", name="secure", local_port=8443)
    assert https["tunnel"]["domain"].endswith(".frp.test")
    assert https["tunnel"]["domain"] != http["tunnel"]["domain"]

    response = await client.get("/api/v1/user", headers=auth(token))
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user["id"]
    assert len(data["tunnels"]) == 4
    assert {item["type"] for item in data["tunnels"]} == {"tcp", "udp", "http", "https"}


async def test_tunnel_limit_and_delete(client):
    await register(client)
    token = await login(client)

    for index in range(10):
        tunnel_type = "tcp" if index < 5 else "http"
        await create_tunnel(client, token, tunnel_type, name=f"t{index}", local_port=1000 + index)

    response = await client.post(
        "/api/v1/tunnels",
        json={"type": "http", "name": "extra", "local_ip": "127.0.0.1", "local_port": 9000},
        headers=auth(token),
    )
    assert response.status_code == 409

    response = await client.get("/api/v1/tunnels", headers=auth(token))
    assert len(response.json()) == 10
    first_id = response.json()[0]["id"]

    response = await client.delete(f"/api/v1/tunnels/{first_id}", headers=auth(token))
    assert response.status_code == 204

    response = await client.get("/api/v1/tunnels", headers=auth(token))
    assert len(response.json()) == 9

    await create_tunnel(client, token, "http", name="again", local_port=8080)


async def test_cannot_delete_other_users_tunnel(client):
    await register(client, "alice")
    alice_token = await login(client, "alice")
    tunnel = await create_tunnel(client, alice_token)

    await register(client, "bob")
    bob_token = await login(client, "bob")

    response = await client.delete(
        f"/api/v1/tunnels/{tunnel['tunnel']['id']}", headers=auth(bob_token)
    )
    assert response.status_code == 404
