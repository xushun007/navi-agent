# Navi Agent

[English](README.md) | 简体中文

Navi Agent 是一个参考 Hermes 思路构建的自我进化 Agent 项目，但当前只保留最核心的产品目标与架构方向。

## 目标

- 可持续优化的 Agent
- 最小闭环：接入、执行、反馈、进化
- 先跑通单入口、单主链路

## 当前范围

- `gateway` 只接微信
- 只保留核心运行链路
- 优先单 Agent 稳定执行

## 自我进化

基于真实运行数据持续发现问题、评估方案、验证改进。

## 微信网关

当前微信网关只保留 iLink 本地轮询风格，拉取文本消息并发送文本回复。

```bash
uv run navi-agent --gateway weixin
```

微信网关只从 `config.yaml` 或环境变量读取配置：

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

`dm_policy` 可选值：

- `open`：所有私聊用户可直接进入 Agent。
- `pairing`：未知私聊用户先收到 pairing code，批准后才进入 Agent。
- `allowlist`：只允许 `allowed_users` 中的用户。
- `disabled`：禁用私聊入口。

pairing 模式下，用户首次私聊会收到批准命令提示。也可以手动查看和批准：

```bash
uv run navi-agent --gateway-pairings weixin
uv run navi-agent --approve-gateway-pairing 123456
```

当前先保留文本消息和私聊授权的最小闭环，其他能力后续再补。

## 一句话定义

Navi Agent = 一个以微信为起点、以持续进化为目标的最小 Agent 内核。

## 命令

```bash
uv run navi-agent --workflow-kind ifeval --workflow-phase review
uv run navi-agent --workflow-kind ifeval --workflow-phase run
uv run navi-agent --workflow-kind ifeval --workflow-phase report
uv run navi-agent --workflow-kind healthcheck --workflow-phase run --workflow-name agent-healthcheck
```

## 评测

- 在线会话进 runtime，离线只看稳定样本
- IFEval 用统一 workflow 跑分并写报告
- 新样本先人工确认，再进 `data/eval/` 回归
