# Navi Agent

Navi Agent 是一个参考 Hermes 思路构建的自我进化 Agent 项目，但当前只保留最核心的产品目标与架构方向。

## 目标

- 构建一个可持续优化的 Agent，而不是一次性脚本
- 聚焦最小可行闭环：接入、执行、反馈、进化
- 先把单入口、单主链路跑通，再逐步扩展能力

## 当前范围

- `gateway` 第一阶段只接入微信
- 只保留核心运行链路，不追求大而全平台
- 优先支持单 Agent 的稳定执行与持续优化

## 自我进化的含义

这里的“自我进化”不是无约束自修改，而是基于真实运行数据持续发现问题、评估方案、验证改进，并逐步提升效果。

## 后续方向

- 打通微信入口
- 建立最小运行时闭环
- 建立反馈与评估机制
- 支持策略层的持续优化
- `--compare-workflow` / `--evolution-run` / `--curator-run` / `--apply-candidate-run` 可加 `--confirm-eval-case`，先人工确认再把结果入库为 `EvalCase`
- 真实 `console` / 微信会话若命中失败、空回复、重复工具、超时或审批阻塞，会自动生成 `target=eval_case` 的候选，使用 `--list-candidates` 和 `--accept-candidate` / `--reject-candidate` 复核
- 也可以直接用 `--review-eval-case` 交互确认最新的待处理 `eval_case` 候选，默认确认/拒绝两步走

## 微信网关

当前微信网关只保留 iLink 本地轮询风格，参考 Hermes 的接入方式，使用 iLink token 拉取文本消息并发送文本回复。

```bash
uv run navi-agent --gateway weixin
```

微信网关只从 `config.yaml` 或环境变量读取配置，推荐写入 `config.yaml`：

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

当前先保留文本消息和私聊授权的最小闭环，登录、媒体、群策略和更完整的账号态管理后续再补。

## 一句话定义

Navi Agent = 一个以微信为起点、以持续进化为目标的最小 Agent 内核。
