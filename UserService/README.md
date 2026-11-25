# FireflyFrp User Service

FastAPI backend for FireflyFrp: user accounts, tunnels, frps plugin authentication,
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
- The FireflyFrp frps fork with live traffic counters and the kick/bandwidth admin APIs

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
DATABASE_URL="mysql+pymysql://qz:password@127.0.0.1:3306/fireflyfrp" alembic upgrade head
```

## HTTPS

Set `server.enable_https = true`, point `server.tls_cert_file` and
`server.tls_key_file` at a PEM cert/key, and use an HTTPS port (for example
`8443`). If no certificate exists, set `server.tls_self_signed = true` to
generate one at startup, or generate it explicitly:

```bash
python -m app.tls --host frp-api.example.com --host 127.0.0.1 \
  --cert certs/server.crt --key certs/server.key
```

`server.tls_hosts` controls the SAN list. When the user service uses HTTPS,
the frps `[[httpPlugins]]` address must be `https://...`; for a self-signed
certificate set `tlsVerify = false` (or install the certificate as trusted).

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
name = "fireflyfrp-user-service"
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
- `PATCH /api/v1/tunnels/{id}` (rename or change the local endpoint)
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
