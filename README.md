# Navi Agent

English | [简体中文](README.zh-CN.md) | [Documentation](https://www.agent-io.com/navi-agent/)

Navi Agent is a compact, self-evolving agent runtime inspired by Hermes. It focuses on a
single reliable execution pipeline across runtime, tools, memory, telemetry, and evolution,
with WeChat as the first gateway.

## Quickstart

```bash
uv tool install git+https://github.com/xushun007/navi-agent.git
navi-agent init
navi-agent doctor
navi-agent
```

Start the WeChat gateway:

```bash
navi-agent doctor --doctor-gateway weixin
navi-agent gateway start
```

Navi Agent stores config and runtime data under `~/.navi-agent`. Use
`NAVI_PROFILE=work` for an isolated profile or `NAVI_HOME=/custom/path` for a
custom location.

Allow access to additional directories explicitly:

```bash
navi-agent --add-dir ../shared --add-dir /path/to/repo
```

## WeChat

Configure `~/.navi-agent/config.yaml`:

```yaml
gateway:
  weixin:
    token: your-token
    account_id: your-account-id
    base_url: https://ilinkai.weixin.qq.com
    dm_policy: pairing
    allowed_users: []
```

`dm_policy` supports `open`, `pairing`, `allowlist`, and `disabled`. Manage
pairing requests with:

```bash
navi-agent --gateway-pairings weixin
navi-agent --approve-gateway-pairing 123456
```

## Evaluation

Inspect evaluations use the production Navi runtime and write replayable results
under `~/.navi-agent/evals/inspect/`.

```bash
uv sync --extra eval
uv run navi-agent eval run general-qa
uv run navi-agent eval run human-eval
uv run navi-agent eval run bfcl
uv run navi-agent eval run agentbench-os
uv run navi-agent eval run swe-bench-verified --limit 1
```

See [evals/README.md](evals/README.md) for suites and usage.

## Development

```bash
uv sync
uv run pytest
uv run navi-agent
```
