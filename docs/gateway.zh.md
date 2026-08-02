# 微信网关

网关将微信消息适配到运行时，不负责规划、工具执行、记忆或响应生成。

## 配置

在 `~/.navi-agent/config.yaml` 中添加微信账号：

```yaml
gateway:
  weixin:
    token: your-token
    account_id: your-account-id
    base_url: https://ilinkai.weixin.qq.com
    poll_interval_seconds: 1.0
    dm_policy: pairing
    allowed_users: []
```

启动前检查连通性：

```bash
navi-agent doctor --doctor-gateway weixin
navi-agent gateway start
```

## 私聊策略

| 策略 | 行为 |
| --- | --- |
| `open` | 接受任意用户的消息 |
| `pairing` | 需要一次性配对审批 |
| `allowlist` | 仅接受 `allowed_users` 中的用户 |
| `disabled` | 拒绝私聊消息 |

在 Pairing 模式中，新发送者会收到配对码。在控制台查看并批准请求：

```bash
navi-agent --gateway-pairings weixin
navi-agent --approve-gateway-pairing 123456
```

## 发送失败

发送失败的消息会被保留，用于检查和重试：

```bash
navi-agent gateway dead-letters
navi-agent gateway retry-dead-letter OUTBOX_ID
```

这可以避免短暂的网关故障导致响应静默丢失。
