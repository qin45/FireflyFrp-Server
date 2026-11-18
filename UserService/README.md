# QZ-FRP User Service

FastAPI backend for QZ-FRP: user accounts, tunnels, frps plugin authentication,
traffic accounting, quota enforcement and shared bandwidth limits.

中文文档（含完整配置说明）：[README_zh.md](README_zh.md)

HTTP/HTTPS tunnels can be disabled on nodes that do not expose vhost ports:

```toml
[limits]
enable_http_tunnels = false
enable_https_tunnels = false
```

## Requirements

- Python 3.11+
- MySQL 8.0+ for production (SQLite is supported for local development/tests)
- The QZ-FRP frps fork with live traffic counters and the kick/bandwidth admin APIs

## Setup

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp config.example.toml config.toml
# edit config.toml

# Production MySQL schema:
alembic upgrade head
# (For local development the app also runs create_all on startup.)

python run.py
```

`run.py` uses `server.host` / `server.port` from `config.toml`. Run exactly
**one process/worker**: the billing poller is an in-process background task.
Multi-worker deployments should move the poller to a separate process protected
by a MySQL advisory lock. If you prefer the uvicorn CLI, pass
`--workers 1` explicitly.

For Alembic, the database URL is read from `config.toml`, or can be overridden:

```bash
DATABASE_URL="mysql+pymysql://qz:password@127.0.0.1:3306/qz_frp" alembic upgrade head
```

## frps configuration

```toml
trafficStatsUpdateIntervalSeconds = 1
subDomainHost = "frp.example.com"
vhostHTTPPort = 80
vhostHTTPSPort = 443

webServer.addr = "127.0.0.1"
webServer.port = 7500
webServer.user = "admin"
webServer.password = "..."
auth.token = "shared-frps-token"

[[httpPlugins]]
name = "qz-user-service"
addr = "127.0.0.1:8080"
path = "/internal/frps/plugin/replace-with-a-random-plugin-secret"
ops = ["Login", "NewProxy", "Ping", "NewUserConn", "CloseProxy"]
```

If nginx/Caddy sits in front of the user service, deny `/internal/`:

```nginx
location /internal/ { deny all; }
```

## API outline

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/password`
- `GET /api/v1/user`
- `GET/POST /api/v1/tunnels`
- `DELETE /api/v1/tunnels/{id}`
- `POST /api/v1/tunnels/{id}/token`
- `GET/PATCH /api/v1/admin/users/{id}`
- `POST /api/v1/admin/users/{id}/kick`

New users start with 0 traffic. An administrator must grant traffic via
`PATCH /api/v1/admin/users/{id}` before their frpc clients can log in.

## Tests

```bash
pytest -q
ruff check .
```

Tests use an isolated SQLite database and a fake frps Admin API. MySQL
integration tests should be run separately against a real MySQL instance.
