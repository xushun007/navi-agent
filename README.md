# Navi Agent

English | [简体中文](README.zh-CN.md)

Navi Agent is a self-evolving agent project inspired by Hermes, but it currently keeps only the core product goals and architectural direction.

## Goals

- A continuously improvable agent
- Minimal closed loop: gateway, execution, feedback, evolution
- Get a single entry point and a single main pipeline working first

## Current Scope

- `gateway` only integrates WeChat
- Only the core runtime pipeline is kept
- Prioritize stable single-agent execution

## Quickstart

Install from source:

```bash
uv tool install git+https://github.com/xushun007/navi-agent.git
```

Initialize local config, check readiness, then start the WeChat gateway:

```bash
navi-agent init
navi-agent doctor
navi-agent doctor --doctor-gateway weixin
navi-agent start
```

Run local interactive chat:

```bash
navi-agent
```

When developing from this repository, prefix commands with `uv run`:

```bash
uv run navi-agent init
uv run navi-agent doctor
uv run navi-agent doctor --doctor-gateway weixin
uv run navi-agent start
uv run navi-agent
```

## Self-Evolution

Continuously discover issues, evaluate solutions, and validate improvements based on real runtime data.

## WeChat Gateway

The current WeChat gateway only keeps the iLink local polling style: it pulls text messages and sends text replies.

```bash
navi-agent start
```

The WeChat gateway reads configuration only from `config.yaml` or environment variables:

```yaml
gateway:
  weixin:
    token: replace-with-your-weixin-token
    account_id: replace-with-your-weixin-account-id
    base_url: https://ilinkai.weixin.qq.com
    poll_interval_seconds: 1.0
    dm_policy: pairing
    allowed_users: []
```

Available `dm_policy` values:

- `open`: all DM users can access the agent directly.
- `pairing`: unknown DM users first receive a pairing code and can access the agent only after approval.
- `allowlist`: only users in `allowed_users` are allowed.
- `disabled`: the DM entry is disabled.

In pairing mode, a user receives an approval command hint on their first DM. You can also list and approve pairings manually:

```bash
uv run navi-agent --gateway-pairings weixin
uv run navi-agent --approve-gateway-pairing 123456
```

For now, only the minimal closed loop of text messages and DM authorization is kept; other capabilities will be added later.

## One-Line Definition

Navi Agent = a minimal agent kernel that starts from WeChat and aims for continuous evolution.

## Commands

```bash
uv run navi-agent --workflow-kind ifeval --workflow-phase review
uv run navi-agent --workflow-kind ifeval --workflow-phase run
uv run navi-agent --workflow-kind ifeval --workflow-phase report
uv run navi-agent --workflow-kind healthcheck --workflow-phase run --workflow-name agent-healthcheck
```

## Evaluation

- Online sessions go through the runtime; offline evaluation only uses stable samples
- IFEval runs scoring through the unified workflow and writes reports
- New samples are manually confirmed first, then added to the `data/eval/` regression set
