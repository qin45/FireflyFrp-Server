from __future__ import annotations

from httpx import AsyncClient

ADMIN_HEADERS = {"Authorization": "Bearer admin-token"}


class FakeFrps:
    def __init__(self) -> None:
        self.proxies: list[dict] = []
        self.kicks: list[str] = []
        self.bandwidth: list[tuple[str, int]] = []

    async def get_proxies(self, status: str = "all") -> list[dict]:
        return list(self.proxies)

    async def get_online_remote_ports(self) -> set[int]:
        ports: set[int] = set()
        for proxy in self.proxies:
            if (proxy.get("status") or {}).get("phase") != "online":
                continue
            spec = proxy.get("spec") or {}
            for proxy_type in ("tcp", "udp"):
                remote_port = (spec.get(proxy_type) or {}).get("remotePort")
                if remote_port:
                    ports.add(int(remote_port))
        return ports

    async def get_online_domains(self) -> set[str]:
        domains: set[str] = set()
        for proxy in self.proxies:
            if (proxy.get("status") or {}).get("phase") != "online":
                continue
            spec = proxy.get("spec") or {}
            for proxy_type in ("http", "https"):
                block = spec.get(proxy_type) or {}
                for domain in block.get("customDomains") or []:
                    domains.add(str(domain).lower())
                subdomain = block.get("subdomain")
                if subdomain:
                    domains.add(f"{subdomain}.frp.test".lower())
        return domains

    async def get_proxy(self, name: str) -> dict | None:
        for proxy in self.proxies:
            if proxy.get("name") == name:
                return proxy
        return None

    async def kick_client(self, key: str) -> bool:
        self.kicks.append(key)
        return True

    async def set_user_bandwidth(self, username: str, bytes_per_second: int) -> bool:
        self.bandwidth.append((username, bytes_per_second))
        return True

    async def close(self) -> None:
        return None


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(
    client: AsyncClient, username: str = "alice", password: str = "password123"
) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login(
    client: AsyncClient, username: str = "alice", password: str = "password123"
) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def grant_traffic(
    client: AsyncClient, user_id: int, remaining_traffic_bytes: int
) -> dict:
    response = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"remaining_traffic_bytes": remaining_traffic_bytes},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def create_tunnel(
    client: AsyncClient,
    token: str,
    tunnel_type: str = "tcp",
    name: str = "test",
    local_port: int = 22,
) -> dict:
    response = await client.post(
        "/api/v1/tunnels",
        json={
            "type": tunnel_type,
            "name": name,
            "local_ip": "127.0.0.1",
            "local_port": local_port,
        },
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def plugin_call(
    client: AsyncClient, op: str, content: dict, secret: str = "plugin-secret"
) -> dict:
    response = await client.post(
        f"/internal/frps/plugin/{secret}?op={op}",
        json={"version": "0.1.0", "op": op, "content": content},
    )
    assert response.status_code == 200, response.text
    return response.json()


def login_content(username: str, tunnel: dict, token: str, run_id: str = "run-1") -> dict:
    return {
        "user": username,
        "client_id": tunnel["tunnel"]["id"],
        "metas": {"token": token, "tunnel_id": tunnel["tunnel"]["id"]},
        "run_id": run_id,
        "timestamp": 0,
        "privilege_key": "",
    }


def new_proxy_content(
    username: str, tunnel: dict, token: str, run_id: str = "run-1"
) -> dict:
    item = tunnel["tunnel"]
    content = {
        "user": {
            "user": username,
            "metas": {"token": token, "tunnel_id": item["id"]},
            "run_id": run_id,
        },
        "proxy_name": f"{username}.{item['id']}",
        "proxy_type": item["type"],
        "bandwidth_limit": "",
        "bandwidth_limit_mode": "",
        "custom_domains": [],
        "subdomain": "",
    }
    if item["type"] in ("tcp", "udp"):
        content["remote_port"] = item["remote_port"]
    else:
        content["subdomain"] = item["subdomain"]
    return content


def proxy_status(
    username: str,
    tunnel_id: str,
    phase: str = "online",
    traffic_in: int = 0,
    traffic_out: int = 0,
) -> dict:
    return {
        "name": f"{username}.{tunnel_id}",
        "status": {
            "phase": phase,
            "todayTrafficIn": traffic_in,
            "todayTrafficOut": traffic_out,
        },
        "spec": {},
    }
