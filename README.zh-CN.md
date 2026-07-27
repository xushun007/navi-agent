# Navi Agent

[English](README.md) | 简体中文

Navi Agent 是一个参考 Hermes 构建的轻量、自我进化 Agent Runtime。项目聚焦 runtime、
tools、memory、telemetry、evolution 组成的单一可靠执行链路，并以微信作为首个 gateway。

## 快速开始

```bash
uv tool install git+https://github.com/xushun007/navi-agent.git
navi-agent init
navi-agent doctor
navi-agent
```

启动微信网关：

```bash
navi-agent doctor --doctor-gateway weixin
navi-agent gateway start
```

配置与运行数据默认存放在 `~/.navi-agent`。使用 `NAVI_PROFILE=work` 隔离不同环境，
或通过 `NAVI_HOME=/custom/path` 指定目录。

显式允许访问其他目录：

```bash
navi-agent --add-dir ../shared --add-dir /path/to/repo
```

## 微信

配置 `~/.navi-agent/config.yaml`：

```yaml
gateway:
  weixin:
    token: your-token
    account_id: your-account-id
    base_url: https://ilinkai.weixin.qq.com
    dm_policy: pairing
    allowed_users: []
```

`dm_policy` 支持 `open`、`pairing`、`allowlist` 和 `disabled`。查看并批准配对：

```bash
navi-agent --gateway-pairings weixin
navi-agent --approve-gateway-pairing 123456
```

## 评测

Inspect 评测复用生产环境的 Navi Runtime，结果写入
`~/.navi-agent/evals/inspect/`，支持离线回放。

```bash
uv sync --extra eval
uv run navi-agent eval run general-qa
uv run navi-agent eval run human-eval
uv run navi-agent eval run bfcl
uv run navi-agent eval run agentbench-os
uv run navi-agent eval run swe-bench-verified --limit 1
```

详细说明见 [evals/README.md](evals/README.md)。

## 开发

```bash
uv sync
uv run pytest
uv run navi-agent
```
