# QZ-FRP 用户服务后端

QZ-FRP 用户服务是一个基于 **FastAPI + SQLAlchemy async + MySQL** 的后端，配合 QZ-FRP 的 frps fork 使用，提供：

- 用户注册、登录、修改密码
- 隧道创建/删除/查询（TCP、UDP、HTTP、HTTPS）
- 每条隧道独立令牌，frpc 通过 frps 插件鉴权
- 按用户共享的流量池与限速
- 流量耗尽自动踢出隧道
- 管理员修改用户剩余流量、限速、密码、状态
- 本地配置文件 + MySQL 用户数据

> 英文版：[README.md](README.md)

---

## 1. 功能概览

| 功能 | 说明 |
|---|---|
| 用户认证 | 用户名 + 密码；bcrypt 加盐哈希；平台 session token |
| 用户信息 | 隧道列表、已用/剩余流量、限速、并发隧道数 |
| 隧道管理 | 最多 10 条；TCP/UDP 分配端口；HTTP/HTTPS 分配子域名 |
| frpc 鉴权 | frps 插件 `Login`/`NewProxy`/`Ping`/`NewUserConn`/`CloseProxy` |
| 并发限制 | 单个用户最多同时开启 3 条隧道 |
| 默认限速 | 注册后 10 Mbps；同一用户所有隧道共享 |
| 流量计费 | 后台轮询 frps 实时流量，按用户累计 |
| 配额执行 | 流量用尽后踢出该用户所有活跃隧道，其他用户不受影响 |
| 管理员接口 | 修改剩余流量、总配额、限速、密码、启用/禁用 |
| 隧道类型开关 | 可在不支持 HTTP/HTTPS 的服务器上禁用这两类隧道 |

---

## 2. 目录结构

```
UserService/
  app/
    main.py                 # uvicorn 入口
    factory.py              # FastAPI 应用工厂、lifespan、poller
    config.py               # 读取 config.toml
    db.py                   # async engine/session
    models.py               # SQLAlchemy ORM
    schemas.py              # Pydantic 请求模型
    security.py             # bcrypt、token、限速换算
    deps.py                 # 登录/管理员依赖
    routers/
      auth.py               # 注册/登录/改密/登出
      user.py               # 用户信息
      tunnels.py            # 隧道 CRUD
      admin.py              # 管理员接口
      frps_plugin.py        # frps HTTP 插件入口
    services/
      frps_api.py           # frps Admin API 客户端
      tunnel_service.py     # 端口/域名分配、frpc 配置生成
      plugin_service.py     # 插件业务逻辑
      billing.py            # 流量轮询、配额、踢人
  alembic/                  # 数据库迁移
  tests/                    # pytest 测试
  config.example.toml
  run.py                    # 按 config.toml 启动
```

---

## 3. 快速开始

### 3.1 环境要求

- Python 3.11+
- MySQL 8.0+（生产）；SQLite 可用于本地开发
- 已部署 QZ-FRP frps fork，并开启：
  - frps Admin API（`webServer`）
  - frps 服务端插件
  - `trafficStatsUpdateIntervalSeconds = 1`
  - 共享限速补丁与 `PUT /api/v2/users/{user}/bandwidth` 接口

### 3.2 安装

```bash
cd QZ-FRPS/UserService
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp config.example.toml config.toml
```

### 3.3 初始化数据库

生产 MySQL（推荐）：

```bash
alembic upgrade head
```

本地开发也可以用 SQLite + 启动时自动建表：

```toml
[database]
url = "sqlite+aiosqlite:///./qz_frp.db"

[server]
auto_create_tables = true
```

### 3.4 启动

```bash
python run.py
```

`run.py` 使用配置中的 `server.host` / `server.port` 启动。

> **只能运行一个后端进程/worker**：流量轮询器是进程内后台任务。多 worker 部署需要把 poller 拆成独立进程，并用 MySQL 分布式锁保证只有一个实例。

---

## 4. 配置文件详细说明

配置文件为 `config.toml`，用于存放平台端口、frps 地址、密钥、默认限额等**硬信息**；用户、隧道、会话、计费数据存放在数据库。

### 4.1 `[server]`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `host` | string | `"0.0.0.0"` | 用户服务监听地址。`0.0.0.0` 表示所有网卡；生产建议只监听内网或由 nginx 反代。 |
| `port` | int | `8080` | 用户服务 HTTP 端口，同时也是 frps 插件访问的端口。 |
| `admin_token` | string | 无（必填） | 管理员接口的 Bearer Token。必须设置为足够长的随机字符串。 |
| `session_ttl_hours` | int | `168` | 用户登录 session 有效期（小时），默认 7 天。 |
| `cors_origins` | list[string] | `[]` | 允许跨域的前端源，例如 `["https://panel.example.com"]`；为空表示不启用 CORS。 |
| `auto_create_tables` | bool | `true` | 启动时是否用 SQLAlchemy 自动建表。**生产使用 Alembic 时设为 `false`**，避免绕过迁移版本管理。 |

### 4.2 `[database]`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `url` | string | `"sqlite+aiosqlite:///./qz_frp.db"` | SQLAlchemy async 数据库 URL。生产 MySQL 示例：`mysql+aiomysql://qz:password@127.0.0.1:3306/qz_frp?charset=utf8mb4`。 |

注意：

- 应用使用 `aiomysql` 异步驱动；Alembic 会自动把 URL 转成 `pymysql` 同步驱动。
- MySQL 建议使用 `utf8mb4`。
- 数据库账号只需要目标库的建表/读写权限。

### 4.3 `[frps]`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `api_url` | string | `"http://127.0.0.1:7500"` | frps Admin API 地址，即 frps `webServer` 的地址。后端用它轮询流量、踢人、修改共享限速。 |
| `api_user` | string | `"admin"` | frps `webServer.user`。 |
| `api_password` | string | 无 | frps `webServer.password`。 |
| `public_host` | string | `"127.0.0.1"` | frpc 连接 frps 的公网地址，会写入生成的 frpc 配置的 `serverAddr`。 |
| `bind_port` | int | `7000` | frps 的 `bindPort`，会写入生成的 frpc 配置。 |
| `auth_token` | string | 空 | frps 全局 `auth.token`，会写入生成的 frpc 配置。所有用户共用它，真正的每用户鉴权由插件完成。 |
| `subdomain_host` | string | `"frp.local"` | HTTP/HTTPS 隧道的域名后缀，必须与 frps 的 `subDomainHost` 完全一致。 |
| `vhost_http_port` | int | `80` | frps 的 `vhostHTTPPort`，用于生成 HTTP 隧道公网地址展示。 |
| `vhost_https_port` | int | `443` | frps 的 `vhostHTTPSPort`，用于生成 HTTPS 隧道公网地址展示。 |
| `plugin_path_secret` | string | 无（必填） | 插件路径密钥，必须与 frps `[[httpPlugins]]` 的 `path` 中的 secret 一致。 |
| `plugin_trusted_cidrs` | list[string] | `["127.0.0.1/32", "::1/128"]` | 允许调用插件接口的来源 IP/CIDR。frps 与后端同机保留回环；跨机部署时加入 frps 的出网 IP/CIDR。 |

### 4.4 `[limits]`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `port_range_start` | int | `20000` | TCP/UDP 隧道可分配端口范围起点。必须落在 frps `allowPorts` 范围内。 |
| `port_range_end` | int | `30000` | TCP/UDP 可分配端口范围终点。 |
| `max_tunnels_per_user` | int | `10` | 每个用户最多创建的隧道数（不包含已删除隧道）。 |
| `max_active_tunnels` | int | `3` | 每个用户最多同时开启的隧道数，由 frps 插件在 Login/NewProxy 时检查。 |
| `default_rate_limit_mbps` | int | `10` | 新用户默认限速（Mbps）。`0` 表示不限速。 |
| `default_traffic_quota_bytes` | int | `0` | 新用户默认流量配额（字节）。默认 0 表示注册后不能启动 frpc，必须由管理员充值。 |
| `traffic_poll_interval_seconds` | int | `2` | 流量轮询间隔（秒）。建议 1-3 秒；越小越实时，但 frps Admin API 压力越大。 |
| `enable_http_tunnels` | bool | `true` | 是否允许 HTTP 隧道。设为 `false` 后，不能创建 HTTP 隧道，已有 HTTP 隧道也不能启动。 |
| `enable_https_tunnels` | bool | `true` | 是否允许 HTTPS 隧道。设为 `false` 后，不能创建 HTTPS 隧道，已有 HTTPS 隧道也不能启动。 |

> 如果服务器没有公网 80/443、没有配置泛域名，或者 frps 没有开启 `vhostHTTPPort`/`vhostHTTPSPort`，建议：
>
> ```toml
> [limits]
> enable_http_tunnels = false
> enable_https_tunnels = false
> ```
>
> 这样前端和 frpc 只能使用 TCP/UDP 隧道。`GET /api/v1/user` 会返回 `enabled_tunnel_types`，前端可据此隐藏不可用类型。

### 4.5 完整配置示例

```toml
[server]
host = "0.0.0.0"
port = 8080
admin_token = "replace-with-a-long-random-admin-token"
session_ttl_hours = 168
cors_origins = ["https://panel.example.com"]
auto_create_tables = false

[database]
url = "mysql+aiomysql://qz:password@127.0.0.1:3306/qz_frp?charset=utf8mb4"

[frps]
api_url = "http://127.0.0.1:7500"
api_user = "admin"
api_password = "replace-with-frps-password"
public_host = "frp.example.com"
bind_port = 7000
auth_token = "shared-frps-token"
subdomain_host = "frp.example.com"
vhost_http_port = 80
vhost_https_port = 443
plugin_path_secret = "replace-with-a-random-plugin-secret"
plugin_trusted_cidrs = ["127.0.0.1/32", "::1/128"]

[limits]
port_range_start = 20000
port_range_end = 30000
max_tunnels_per_user = 10
max_active_tunnels = 3
default_rate_limit_mbps = 10
default_traffic_quota_bytes = 0
traffic_poll_interval_seconds = 2
enable_http_tunnels = false
enable_https_tunnels = false
```

---

## 5. frps 配置

frps 需要开启 Admin API、服务端插件和实时流量计数：

```toml
bindAddr = "0.0.0.0"
bindPort = 7000
subDomainHost = "frp.example.com"   # 与 config.toml 的 subdomain_host 一致
vhostHTTPPort = 80                  # 需要 HTTP 隧道时设置
vhostHTTPSPort = 443                # 需要 HTTPS 隧道时设置
trafficStatsUpdateIntervalSeconds = 1
auth.token = "shared-frps-token"

webServer.addr = "127.0.0.1"
webServer.port = 7500
webServer.user = "admin"
webServer.password = "replace-with-frps-password"

[[httpPlugins]]
name = "qz-user-service"
addr = "127.0.0.1:8080"             # 用户服务地址
path = "/internal/frps/plugin/replace-with-a-random-plugin-secret"
ops = ["Login", "NewProxy", "Ping", "NewUserConn", "CloseProxy"]
```

- `trafficStatsUpdateIntervalSeconds` 建议为 `1`，否则长连接流量统计不够实时。
- `subDomainHost`、`vhostHTTPPort`、`vhostHTTPSPort` 只在启用 HTTP/HTTPS 隧道时需要。
- 如果 frps 和后端不在同一台机器：
  - 把 `addr` 改成后端内网地址；
  - 把 frps 出网 IP 加入 `plugin_trusted_cidrs`；
  - 用防火墙限制只有 frps 能访问插件端口。

如果前面有 nginx/Caddy，必须禁止外部访问 `/internal/`：

```nginx
location /internal/ {
    deny all;
}
```

---

## 6. 隧道类型与端口/域名规则

| 类型 | 分配资源 | frpc 配置关键字段 | 公网访问 |
|---|---|---|---|
| `tcp` | 从 `port_range` 分配一个端口 | `remotePort = <y>` | `<public_host>:<y>` |
| `udp` | 从 `port_range` 分配一个端口 | `remotePort = <y>` | `<public_host>:<y>`（UDP） |
| `http` | 分配 `<tunnel_id>.<subdomain_host>` | `subdomain = "<tunnel_id>"` | `http://<domain>` |
| `https` | 分配 `<tunnel_id>.<subdomain_host>` | `subdomain = "<tunnel_id>"` | `https://<domain>` |

- TCP/UDP 的端口由后端在 `[port_range_start, port_range_end]` 内选择，并检查：
  - 数据库中的 `port_reservations`；
  - frps 当前在线代理已占用的端口。
- HTTP/HTTPS 不占用独立端口，使用 frps 的 vhost 端口和域名。
- 删除隧道时会释放端口/域名，允许后续复用。
- 隧道类型创建后不可修改，需要换类型请删除后重建。

> **禁用 HTTP/HTTPS**：
>
> ```toml
> enable_http_tunnels = false
> enable_https_tunnels = false
> ```
>
> 效果：
> - `POST /api/v1/tunnels` 创建对应类型返回 400；
> - 已有 HTTP/HTTPS 隧道在 frpc `Login`/`NewProxy` 时被拒绝；
> - TCP/UDP 不受影响；
> - `/api/v1/user` 的 `enabled_tunnel_types` 只返回 `["tcp","udp"]`。

---

## 7. 流量、配额与限速

### 7.1 流量计费

- 计费口径：**上行 + 下行合计**，单位字节。
- 后端每 `traffic_poll_interval_seconds` 秒读取 frps `/api/v2/proxies` 的 `todayTrafficIn/Out`。
- 增量算法：
  - 正常情况下 `delta = current - last`；
  - 如果 `current < last`，视为跨天或 frps 重启，`delta = current`。
- 新隧道从 0 开始计费；重连隧道用当前计数器作为基线，避免重复计费。
- `CloseProxy` 或代理离线后，后端结束对应 `tunnel_session`，停止该隧道计费。

### 7.2 配额

- 配额是**用户级**，所有隧道共享。
- `剩余流量 = max(0, 总配额 - 已用)`。
- 流量用尽后：
  - 用户状态置为 `exhausted`；
  - 后端调用 frps `POST /api/v2/clients/{user}.{client_id}/kick` 踢出该用户所有活跃隧道；
  - 插件 `Login`/`Ping`/`NewUserConn` 拒绝该用户；
  - 其他用户不受影响。
- 管理员充值后，用户状态自动恢复为 `active`，可重新启动 frpc。

### 7.3 限速

- 默认 10 Mbps，同一用户所有隧道**共享**一个限速器。
- 插件在 `NewProxy` 时强制下发服务端限速，用户不能通过自己的 frpc 配置绕过。
- 管理员修改限速时，后端调用 frps：

```http
PUT /api/v2/users/{user}/bandwidth?bytesPerSecond=<n>
```

- `rate_limit_mbps = 0` 表示不限速。

---

## 8. API 说明

### 8.1 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/register` | 注册：`{"username","password"}` |
| POST | `/api/v1/auth/login` | 登录：返回 Bearer token |
| POST | `/api/v1/auth/password` | 修改密码：`{"old_password","new_password"}` |
| POST | `/api/v1/auth/logout` | 登出当前 session |

### 8.2 用户

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/user` | 用户信息、剩余流量、限速、隧道列表、可用隧道类型 |

### 8.3 隧道

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/tunnels` | 当前用户隧道列表 |
| POST | `/api/v1/tunnels` | 创建隧道：`{"type","name","local_ip","local_port"}` |
| GET | `/api/v1/tunnels/{id}` | 单条隧道 |
| DELETE | `/api/v1/tunnels/{id}` | 删除隧道（活跃时先踢下线） |
| POST | `/api/v1/tunnels/{id}/token` | 轮换隧道令牌 |

创建成功返回隧道信息、隧道 token 和可直接使用的 frpc TOML 配置。**token 只返回一次**。

### 8.4 管理员

管理员接口使用配置中的 `admin_token`：

```http
Authorization: Bearer <admin_token>
```

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/admin/users?page=1&page_size=50&q=` | 用户列表 |
| GET | `/api/v1/admin/users/{id}` | 用户详情 |
| PATCH | `/api/v1/admin/users/{id}` | 修改剩余流量、总配额、限速、密码、状态 |
| POST | `/api/v1/admin/users/{id}/kick` | 踢出该用户所有活跃隧道 |
| GET | `/api/v1/admin/tunnels?user_id=` | 用户的隧道列表 |

PATCH 请求示例：

```json
{
  "remaining_traffic_bytes": 10737418240,
  "rate_limit_mbps": 20,
  "password": "new-password",
  "status": "active"
}
```

字段含义：

- `remaining_traffic_bytes`：设置剩余流量，后端计算 `总配额 = 已用 + 剩余`；
- `traffic_quota_bytes`：直接设置总配额（与上者二选一）；
- `rate_limit_mbps`：修改限速，立即同步到 frps；
- `password`：重置密码，并撤销该用户所有 session；
- `status`：`active` / `disabled` / `exhausted`；`disabled` 会踢出活跃隧道。

### 8.5 插件内部接口

frps 调用：

```http
POST /internal/frps/plugin/<plugin_secret>?op=Login
```

支持 `Login`、`NewProxy`、`Ping`、`NewUserConn`、`CloseProxy`。该接口不应暴露公网。

---

## 9. 数据模型

| 表 | 作用 |
|---|---|
| `users` | 用户、密码哈希、流量配额/已用、限速、状态 |
| `sessions` | 平台登录 session（只存 token 哈希） |
| `tunnels` | 隧道、类型、端口或域名、隧道 token 哈希、状态 |
| `port_reservations` | TCP/UDP 端口占用，保证分配原子性 |
| `tunnel_sessions` | 每次 frpc 启动的会话、run_id、实时流量累计、计费状态 |

---

## 10. 管理员操作流程

1. 用户注册后默认配额为 **0**，此时可以登录平台和创建隧道，但 frpc 会被拒绝。
2. 管理员给用户充值：

```bash
curl -X PATCH http://127.0.0.1:8080/api/v1/admin/users/1 \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"remaining_traffic_bytes": 10737418240}'
```

3. 用户登录平台，获取隧道 token 和 frpc 配置，启动 frpc。
4. 需要限制某用户时：

```bash
# 改限速
curl -X PATCH .../users/1 -d '{"rate_limit_mbps": 5}'

# 禁用账号并踢下线
curl -X PATCH .../users/1 -d '{"status":"disabled"}'
```

---

## 11. 部署建议

### 11.1 单进程运行

```bash
alembic upgrade head
python run.py
```

不要使用多个 uvicorn worker。需要横向扩展时，把 `billing.py` 的轮询器拆成独立服务，并使用 MySQL `GET_LOCK` 或类似机制保证单实例。

### 11.2 systemd 示例

```ini
[Unit]
Description=QZ-FRP User Service
After=network.target mysql.service

[Service]
Type=simple
User=qzfrp
WorkingDirectory=/opt/qz-frp/UserService
Environment=QZ_CONFIG=/opt/qz-frp/UserService/config.toml
ExecStart=/opt/qz-frp/UserService/.venv/bin/python run.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### 11.3 反向代理

- 对外暴露 `/api/v1/`。
- `deny all` 禁止 `/internal/`。
- 建议由 nginx/Caddy 终止 TLS。
- 不要用会改变来源 IP 的代理转发插件路径。

### 11.4 安全

- `admin_token` 使用 32 字节以上随机值。
- 数据库密码、frps 密码、插件 secret 不要提交到仓库。
- `config.toml` 权限设为 `600`。
- 插件端口只允许 frps 访问。
- 定期备份 MySQL。

---

## 12. 测试

```bash
cd QZ-FRPS/UserService
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check app tests run.py
```

当前测试覆盖：

- 注册/登录/改密/session 失效
- 默认配额 0 与管理员充值
- 四种隧道类型、端口/域名分配、10 条上限
- HTTP/HTTPS 隧道禁用开关
- 插件 Login/NewProxy/Ping/CloseProxy
- 3 条活跃隧道限制
- 计费增量、计数器回落、配额耗尽踢人
- 关闭单条隧道不影响其他隧道计费
- 管理员改剩余流量/限速/密码/禁用

生产上线前建议额外做一次 **真实 MySQL** 的集成测试（本仓库默认测试使用 SQLite）。

---

## 13. 已知限制

- 每条隧道需要一个独立 frpc 进程（`clientID = tunnel_id`），这是“只下线单条隧道”的前提。
- 只支持 `tcp` / `udp` / `http` / `https`，不支持 STCP/XTCP/SUDP。
- HTTP/HTTPS 使用 frps 的 vhost 端口和 `<tunnel_id>.<subdomain_host>` 域名，不分配独立端口。
- 流量计数器是 frps 进程内的当日计数；跨天/重启靠“计数器回落”处理，插件侧负责累计。
- 插件是登录/心跳的强依赖：用户服务不可用时 frps 会 fail-closed。
- 生产多 worker/多实例需要额外处理计费 poller 的单实例问题。
