# FireflyFrp 修改版 frps

本目录提供 FireflyFrp 使用的 frps 可执行文件。它们来自修改过的 frp 源码，不是上游原版 frps。

## 来源

- 上游项目：<https://github.com/fatedier/frp>
- 修改源码：<https://github.com/qin45/frp>
- 分支：`feat/live-traffic-kick`
- 提交：`e0f615a77558392adb6d5e01b2228196f20688c8`
- 基线：`bafec21a`（上游 `fatedier/dev` 合并点）
- frps 版本：`0.72.0`

`frp` 使用 Apache License 2.0。本目录同时附带 `LICENSE` 和 `NOTICE`，修改版本的再分发遵循同一许可证。

## 文件

| 文件 | 平台 |
|---|---|
| `frps-linux-amd64` | Linux x86-64，静态链接 |
| `frps-windows-amd64.exe` | Windows x86-64 |

## 修改内容

### 1. 活跃连接实时流量统计

- 新增 `trafficStatsUpdateIntervalSeconds` 配置项，默认 `0` 保持上游行为（连接关闭后计数）。
- 新增 `server/proxy/traffic.go` 与测试：按定时器刷新活跃连接流量，长连接也能在 Admin API、Dashboard 和 Prometheus 中及时看到流量。
- 修改 `server/proxy/proxy.go`、`server/proxy/http.go`，将流量统计包装应用到 TCP/UDP/HTTP 等代理；SUDP 仍按关闭时结算。
- 修改配置文件示例 `conf/frps_full_example.toml` 和配置校验 `pkg/config/v1/...`。

### 2. 按用户共享限速

- 新增 `pkg/util/limit/user_limiter.go`：同一用户的多个隧道共享一个 `golang.org/x/time/rate.Limiter`。
- 修改 `server/proxy/proxy.go`：当代理带有用户信息时，使用用户级共享限速器。
- 修改 `server/controller/resource.go`、`server/service.go`、`server/api_router.go`：注册 `UserLimiters` 并传入 Admin API。
- 新增 `PUT /api/v2/users/{user}/bandwidth?bytesPerSecond=...`，支持运行时调整单用户共享带宽。
- 新增 `POST /api/v2/users/{user}/kick`，按用户踢出全部客户端。
- 新增 `POST /api/v2/clients/{key}/kick`，按 runID 踢出单个客户端。

### 3. 用户流量与强制下线

- 扩展 `server/http/model/v2.go`：用户响应增加 `todayTrafficIn`、`todayTrafficOut`、`curConns`；新增 kick/bandwidth 响应模型。
- 修改 `server/control.go`：增加按 runID 和按用户踢出的控制逻辑。
- 修改 `server/http/controller.go`、`server/http/controller_v2.go` 及测试：实现上述 Admin API。
- 这些接口由 FireflyFrp 用户服务的计费/额度逻辑调用。

## 构建

在修改版 `frp` 源码目录执行：

```bash
# Linux amd64
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath \
  -tags "frps,noweb" -ldflags "-s -w" \
  -o frps-linux-amd64 ./cmd/frps

# Windows amd64
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath \
  -tags "frps,noweb" -ldflags "-s -w" \
  -o frps-windows-amd64.exe ./cmd/frps
```

## 许可证与归属

本目录的二进制和修改说明随 FireflyFrp 分发，但 frps 本身是 frp 的衍生作品，按 **Apache License 2.0** 授权，而不是 FireflyFrp 仓库根部 MIT 许可证。完整许可证见 [LICENSE](LICENSE)，归属声明见 [NOTICE](NOTICE)。
