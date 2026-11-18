from __future__ import annotations

from urllib.parse import quote

import httpx

from ..config import FrpsSettings


class FrpsAPI:
    """Minimal client for the frps v2 Admin API."""

    def __init__(self, settings: FrpsSettings):
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.api_url,
                auth=(self.settings.api_user, self.settings.api_password),
                timeout=5.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_proxies(self, status: str = "all") -> list[dict]:
        page = 1
        items: list[dict] = []
        while True:
            response = await self.client.get(
                "/api/v2/proxies",
                params={"status": status, "page": page, "pageSize": 200},
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            batch = data.get("items") or []
            items.extend(batch)
            total = int(data.get("total") or len(items))
            if not batch or len(items) >= total:
                return items
            page += 1

    async def get_proxy(self, name: str) -> dict | None:
        response = await self.client.get(f"/api/v2/proxies/{quote(name, safe='')}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json().get("data")

    async def get_online_remote_ports(self) -> set[int]:
        ports: set[int] = set()
        for proxy in await self.get_proxies("online"):
            if (proxy.get("status") or {}).get("phase") != "online":
                continue
            spec = proxy.get("spec") or {}
            for proxy_type in ("tcp", "udp"):
                block = spec.get(proxy_type) or {}
                remote_port = block.get("remotePort")
                if remote_port:
                    ports.add(int(remote_port))
        return ports

    async def get_online_domains(self) -> set[str]:
        domains: set[str] = set()
        for proxy in await self.get_proxies("online"):
            if (proxy.get("status") or {}).get("phase") != "online":
                continue
            spec = proxy.get("spec") or {}
            for proxy_type in ("http", "https", "tcpmux"):
                block = spec.get(proxy_type) or {}
                for domain in block.get("customDomains") or []:
                    domains.add(str(domain).lower())
                subdomain = block.get("subdomain")
                if subdomain:
                    domains.add(
                        f"{subdomain}.{self.settings.subdomain_host}".lower()
                    )
        return domains

    async def kick_client(self, key: str) -> bool:
        response = await self.client.post(
            f"/api/v2/clients/{quote(key, safe='')}/kick"
        )
        return response.status_code == 200

    async def set_user_bandwidth(self, username: str, bytes_per_second: int) -> bool:
        response = await self.client.put(
            f"/api/v2/users/{quote(username, safe='')}/bandwidth",
            params={"bytesPerSecond": bytes_per_second},
        )
        return response.status_code == 200
