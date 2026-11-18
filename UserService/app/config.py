from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerSettings:
    host: str = "0.0.0.0"
    port: int = 8080
    admin_token: str = ""
    session_ttl_hours: int = 168
    cors_origins: list[str] = field(default_factory=list)
    # Convenient for local development. Set false in production and use Alembic.
    auto_create_tables: bool = True


@dataclass
class DatabaseSettings:
    url: str = "sqlite+aiosqlite:///./qz_frp.db"


@dataclass
class FrpsSettings:
    api_url: str = "http://127.0.0.1:7500"
    api_user: str = "admin"
    api_password: str = ""
    public_host: str = "127.0.0.1"
    bind_port: int = 7000
    auth_token: str = ""
    subdomain_host: str = "frp.local"
    vhost_http_port: int = 80
    vhost_https_port: int = 443
    plugin_path_secret: str = ""
    plugin_trusted_cidrs: list[str] = field(
        default_factory=lambda: ["127.0.0.1/32", "::1/128"]
    )


@dataclass
class LimitSettings:
    port_range_start: int = 20000
    port_range_end: int = 30000
    max_tunnels_per_user: int = 10
    max_active_tunnels: int = 3
    default_rate_limit_mbps: int = 10
    default_traffic_quota_bytes: int = 0
    traffic_poll_interval_seconds: int = 2
    # Some frps deployments do not expose vhost HTTP/HTTPS ports. Turn these
    # off to reject creation and startup of HTTP/HTTPS tunnels.
    enable_http_tunnels: bool = True
    enable_https_tunnels: bool = True

    def enabled_tunnel_types(self) -> list[str]:
        types = ["tcp", "udp"]
        if self.enable_http_tunnels:
            types.append("http")
        if self.enable_https_tunnels:
            types.append("https")
        return types


@dataclass
class Settings:
    server: ServerSettings = field(default_factory=ServerSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    frps: FrpsSettings = field(default_factory=FrpsSettings)
    limits: LimitSettings = field(default_factory=LimitSettings)


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"config section [{name}] must be a table")
    return value


def _list_str(value: object, default: list[str]) -> list[str]:
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected a list of strings")
    return value


def _bool(value: object, default: bool, name: str) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path or os.environ.get("QZ_CONFIG", "config.toml"))
    with config_path.open("rb") as f:
        data = tomllib.load(f)

    server = _section(data, "server")
    database = _section(data, "database")
    frps = _section(data, "frps")
    limits = _section(data, "limits")

    settings = Settings(
        server=ServerSettings(
            host=str(server.get("host", "0.0.0.0")),
            port=int(server.get("port", 8080)),
            admin_token=str(server.get("admin_token", "")),
            session_ttl_hours=int(server.get("session_ttl_hours", 168)),
            cors_origins=_list_str(server.get("cors_origins"), []),
            auto_create_tables=bool(server.get("auto_create_tables", True)),
        ),
        database=DatabaseSettings(url=str(database.get("url", ""))),
        frps=FrpsSettings(
            api_url=str(frps.get("api_url", "http://127.0.0.1:7500")).rstrip("/"),
            api_user=str(frps.get("api_user", "admin")),
            api_password=str(frps.get("api_password", "")),
            public_host=str(frps.get("public_host", "127.0.0.1")),
            bind_port=int(frps.get("bind_port", 7000)),
            auth_token=str(frps.get("auth_token", "")),
            subdomain_host=str(frps.get("subdomain_host", "frp.local")).lower(),
            vhost_http_port=int(frps.get("vhost_http_port", 80)),
            vhost_https_port=int(frps.get("vhost_https_port", 443)),
            plugin_path_secret=str(frps.get("plugin_path_secret", "")),
            plugin_trusted_cidrs=_list_str(
                frps.get("plugin_trusted_cidrs"), ["127.0.0.1/32", "::1/128"]
            ),
        ),
        limits=LimitSettings(
            port_range_start=int(limits.get("port_range_start", 20000)),
            port_range_end=int(limits.get("port_range_end", 30000)),
            max_tunnels_per_user=int(limits.get("max_tunnels_per_user", 10)),
            max_active_tunnels=int(limits.get("max_active_tunnels", 3)),
            default_rate_limit_mbps=int(limits.get("default_rate_limit_mbps", 10)),
            default_traffic_quota_bytes=int(
                limits.get("default_traffic_quota_bytes", 0)
            ),
            traffic_poll_interval_seconds=int(
                limits.get("traffic_poll_interval_seconds", 2)
            ),
            enable_http_tunnels=_bool(
                limits.get("enable_http_tunnels"), True, "limits.enable_http_tunnels"
            ),
            enable_https_tunnels=_bool(
                limits.get("enable_https_tunnels"), True, "limits.enable_https_tunnels"
            ),
        ),
    )
    _validate(settings)
    return settings


def _validate(settings: Settings) -> None:
    if not settings.database.url:
        raise ValueError("database.url is required")
    if not settings.server.admin_token:
        raise ValueError("server.admin_token is required")
    if not settings.frps.plugin_path_secret:
        raise ValueError("frps.plugin_path_secret is required")
    if not (1 <= settings.server.port <= 65535):
        raise ValueError("server.port must be between 1 and 65535")
    if not (1 <= settings.frps.bind_port <= 65535):
        raise ValueError("frps.bind_port must be between 1 and 65535")
    if not (1 <= settings.frps.vhost_http_port <= 65535):
        raise ValueError("frps.vhost_http_port must be between 1 and 65535")
    if not (1 <= settings.frps.vhost_https_port <= 65535):
        raise ValueError("frps.vhost_https_port must be between 1 and 65535")
    limits = settings.limits
    if limits.port_range_start > limits.port_range_end:
        raise ValueError("limits.port_range_start must be <= port_range_end")
    if not (1 <= limits.port_range_start and limits.port_range_end <= 65535):
        raise ValueError("port range must be within 1..65535")
    if limits.max_tunnels_per_user <= 0:
        raise ValueError("limits.max_tunnels_per_user must be positive")
    if limits.max_active_tunnels <= 0:
        raise ValueError("limits.max_active_tunnels must be positive")
    if limits.max_active_tunnels > limits.max_tunnels_per_user:
        raise ValueError("max_active_tunnels cannot exceed max_tunnels_per_user")
    if limits.default_rate_limit_mbps < 0:
        raise ValueError("default_rate_limit_mbps must be non-negative")
    if limits.default_traffic_quota_bytes < 0:
        raise ValueError("default_traffic_quota_bytes must be non-negative")
    if limits.traffic_poll_interval_seconds <= 0:
        raise ValueError("traffic_poll_interval_seconds must be positive")
