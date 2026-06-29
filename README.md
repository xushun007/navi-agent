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

## 微信网关

当前已经具备最小微信 webhook 原型，可用于公众号回调接入与文本消息收发。

启动示例：

```bash
uv run navi-agent --weixin-gateway --weixin-token replace-with-your-weixin-token
```

如果不传 `--weixin-token`，也可以写入 `config.yaml`：

```yaml
gateway:
  weixin:
    token: replace-with-your-weixin-token
    host: 127.0.0.1
    port: 8080
```

微信服务器回调将由 `GET` 验签和 `POST` XML 消息处理组成，当前先保留文本消息的最小闭环。

## 一句话定义

Navi Agent = 一个以微信为起点、以持续进化为目标的最小 Agent 内核。
