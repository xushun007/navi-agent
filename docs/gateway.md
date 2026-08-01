# Weixin Gateway

The gateway adapts Weixin messages to the runtime. It does not own planning,
tool execution, memory, or response generation.

## Configure

Add the Weixin account to `~/.navi-agent/config.yaml`:

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

Check connectivity before starting:

```bash
navi-agent doctor --doctor-gateway weixin
navi-agent gateway start
```

## Direct-message policies

| Policy | Behavior |
| --- | --- |
| `open` | Accept messages from any user |
| `pairing` | Require a one-time pairing approval |
| `allowlist` | Accept only configured `allowed_users` |
| `disabled` | Reject direct messages |

For pairing mode, a new sender receives a code. Review and approve pending
requests from the console:

```bash
navi-agent --gateway-pairings weixin
navi-agent --approve-gateway-pairing 123456
```

## Delivery failures

Failed outbound messages are retained for inspection and retry:

```bash
navi-agent gateway dead-letters
navi-agent gateway retry-dead-letter OUTBOX_ID
```

This prevents a transient gateway failure from silently discarding a response.
