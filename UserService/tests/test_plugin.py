from __future__ import annotations

from tests.helpers import (
    auth,
    create_tunnel,
    grant_traffic,
    login,
    login_content,
    new_proxy_content,
    plugin_call,
    register,
)


async def test_plugin_health_probe(client):
    response = await client.get("/internal/frps/plugin/plugin-secret/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True

    response = await client.get("/internal/frps/plugin/wrong-secret/health")
    assert response.status_code == 404


async def test_quota_bandwidth_and_ping(client):
    user = await register(client)
    token = await login(client)
    tunnel = await create_tunnel(client, token, "tcp")
    content = login_content("alice", tunnel, tunnel["token"])

    result = await plugin_call(client, "Login", content)
    assert result["reject"] is True
    assert "traffic" in result["reject_reason"]

    await grant_traffic(client, user["id"], 1_000_000)
    result = await plugin_call(client, "Login", content)
    assert result["reject"] is False

    bad_proxy = new_proxy_content("alice", tunnel, tunnel["token"])
    bad_proxy["remote_port"] += 1
    result = await plugin_call(client, "NewProxy", bad_proxy)
    assert result["reject"] is True
    assert "port" in result["reject_reason"]

    proxy = new_proxy_content("alice", tunnel, tunnel["token"])
    result = await plugin_call(client, "NewProxy", proxy)
    assert result["reject"] is False
    assert result["content"]["bandwidth_limit"] == "1220.7031KB"
    assert result["content"]["bandwidth_limit_mode"] == "server"

    ping = {"user": {"user": "alice", "metas": content["metas"], "run_id": "run-1"}}
    result = await plugin_call(client, "Ping", ping)
    assert result["reject"] is False

    await grant_traffic(client, user["id"], 0)
    result = await plugin_call(client, "Ping", ping)
    assert result["reject"] is True


async def test_active_tunnel_limit_and_close_proxy(client):
    user = await register(client)
    await grant_traffic(client, user["id"], 10_000_000)
    token = await login(client)

    tunnels = [
        await create_tunnel(client, token, "tcp", name=f"t{i}", local_port=22)
        for i in range(4)
    ]

    for index in range(3):
        run_id = f"run-{index}"
        result = await plugin_call(
            client,
            "Login",
            login_content("alice", tunnels[index], tunnels[index]["token"], run_id),
        )
        assert result["reject"] is False
        result = await plugin_call(
            client,
            "NewProxy",
            new_proxy_content("alice", tunnels[index], tunnels[index]["token"], run_id),
        )
        assert result["reject"] is False

    result = await plugin_call(
        client,
        "Login",
        login_content("alice", tunnels[3], tunnels[3]["token"], "run-3"),
    )
    assert result["reject"] is True
    assert "active tunnels" in result["reject_reason"]

    response = await client.get("/api/v1/user", headers=auth(token))
    active = [item for item in response.json()["tunnels"] if item["active"]]
    assert len(active) == 3

    result = await plugin_call(
        client,
        "CloseProxy",
        {
            "user": {
                "user": "alice",
                "metas": {"token": tunnels[0]["token"], "tunnel_id": tunnels[0]["tunnel"]["id"]},
                "run_id": "run-0",
            },
            "proxy_name": f"alice.{tunnels[0]['tunnel']['id']}",
        },
    )
    assert result["reject"] is False

    response = await client.get("/api/v1/user", headers=auth(token))
    by_id = {item["id"]: item for item in response.json()["tunnels"]}
    assert by_id[tunnels[0]["tunnel"]["id"]]["active"] is False
    assert by_id[tunnels[1]["tunnel"]["id"]]["active"] is True
    assert by_id[tunnels[2]["tunnel"]["id"]]["active"] is True


async def test_http_tunnel_domain_validation(client):
    user = await register(client, "bob")
    await grant_traffic(client, user["id"], 10_000_000)
    token = await login(client, "bob")
    tunnel = await create_tunnel(client, token, "http", name="web", local_port=8080)

    proxy = new_proxy_content("bob", tunnel, tunnel["token"])
    proxy["subdomain"] = "wrong"
    result = await plugin_call(client, "NewProxy", proxy)
    assert result["reject"] is True
    assert "domain" in result["reject_reason"]

    proxy = new_proxy_content("bob", tunnel, tunnel["token"])
    result = await plugin_call(client, "NewProxy", proxy)
    assert result["reject"] is False


async def test_disabled_http_tunnel_is_rejected_on_login(client, app):
    user = await register(client, "carol")
    await grant_traffic(client, user["id"], 10_000_000)
    token = await login(client, "carol")
    tunnel = await create_tunnel(client, token, "http", name="web", local_port=8080)

    app.state.settings.limits.enable_http_tunnels = False
    result = await plugin_call(
        client, "Login", login_content("carol", tunnel, tunnel["token"])
    )
    assert result["reject"] is True
    assert "disabled" in result["reject_reason"]


async def test_invalid_token_rejected(client):
    user = await register(client)
    await grant_traffic(client, user["id"], 1_000_000)
    token = await login(client)
    tunnel = await create_tunnel(client, token)

    content = login_content("alice", tunnel, "wrong-token")
    result = await plugin_call(client, "Login", content)
    assert result["reject"] is True
    assert "token" in result["reject_reason"]
