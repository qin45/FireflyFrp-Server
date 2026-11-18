from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import (
    DatabaseSettings,
    FrpsSettings,
    LimitSettings,
    ServerSettings,
    Settings,
)
from app.db import close_engine, init_db
from app.factory import create_app
from tests.helpers import FakeFrps


@pytest_asyncio.fixture
async def app(tmp_path):
    settings = Settings(
        server=ServerSettings(
            admin_token="admin-token",
            session_ttl_hours=24,
        ),
        database=DatabaseSettings(
            url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        ),
        frps=FrpsSettings(
            api_url="http://frps.test",
            api_user="admin",
            api_password="admin",
            public_host="frp.test",
            bind_port=7000,
            auth_token="shared-token",
            subdomain_host="frp.test",
            vhost_http_port=80,
            vhost_https_port=443,
            plugin_path_secret="plugin-secret",
            plugin_trusted_cidrs=["127.0.0.1/32", "::1/128"],
        ),
        limits=LimitSettings(
            port_range_start=20000,
            port_range_end=20010,
            max_tunnels_per_user=10,
            max_active_tunnels=3,
            default_rate_limit_mbps=10,
            default_traffic_quota_bytes=0,
            traffic_poll_interval_seconds=1,
        ),
    )
    application = create_app(settings, start_poller=False)
    application.state.frps = FakeFrps()
    await init_db()
    yield application
    await close_engine()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
