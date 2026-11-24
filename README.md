# FireflyFrp Server

FireflyFrp（萤火内网穿透）服务端仓库，包含用户服务后端和修改版 frps 二进制。

## 目录

| 路径 | 说明 |
|---|---|
| `UserService/` | FastAPI + SQLAlchemy async + MySQL/SQLite 用户服务，提供注册/登录、隧道管理、流量额度、限速和管理员接口。 |
| `frps/` | FireflyFrp 修改版 frps（Linux/Windows amd64）及其 Apache-2.0 归属说明。 |

## 相关仓库

- 客户端：<https://github.com/qin45/FireflyFrp-Client>
- 修改版 frp 源码：<https://github.com/qin45/frp>

## 快速开始

用户服务部署、配置和接口文档见：

- [UserService/README_zh.md](UserService/README_zh.md)
- [UserService/README.md](UserService/README.md)

frps 修改内容、构建方式和许可证说明见：

- [frps/README.md](frps/README.md)
- [frps/NOTICE](frps/NOTICE)

## 许可证

- `UserService/` 及本仓库自有代码：MIT，见 [LICENSE](LICENSE)。
- `frps/` 下的修改版 frps：Apache License 2.0，见 [frps/LICENSE](frps/LICENSE) 和 [frps/NOTICE](frps/NOTICE)。
