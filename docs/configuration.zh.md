# 配置

Navi Agent 默认从 `~/.navi-agent/config.yaml` 读取 YAML 配置。环境变量的优先级高于配置文件。

## 配置文件

```yaml
model:
  name: gpt-4o-mini
  api_key: replace-with-your-api-key
  base_url: https://api.openai.com/v1
  context_limit_tokens: 128000

runtime:
  max_iterations: 30

web:
  search_api_key: replace-with-your-brave-search-api-key

mcp:
  servers: {}

gateway:
  weixin:
    token: replace-with-your-weixin-token
    account_id: replace-with-your-weixin-account-id
    base_url: https://ilinkai.weixin.qq.com
    poll_interval_seconds: 1.0
    dm_policy: pairing
    allowed_users: []

telemetry:
  langfuse:
    enabled: false
    public_key: replace-with-your-langfuse-public-key
    secret_key: replace-with-your-langfuse-secret-key
    host: https://cloud.langfuse.com
```

## MCP 工具

第一版 MCP 仅支持本地 `stdio` Server，并只接入其 Tools。先安装可选依赖：

```bash
uv sync --extra mcp
```

然后在配置中声明 Server：

```yaml
mcp:
  servers:
    files:
      command:
        - npx
        - -y
        - "@modelcontextprotocol/server-filesystem"
        - /absolute/path/to/project
      environment:
        ACCESS_TOKEN: "${ACCESS_TOKEN}"
      startup_timeout_seconds: 10
      tool_timeout_seconds: 30
```

环境变量引用只接受完整的 `${NAME}` 形式，实际值不会写入配置。发现的工具以
`mcp__files__工具名` 注册。某个 Server 启动失败时只禁用该 Server，不阻断 Navi
启动。当前不支持 remote HTTP、resources、prompts、OAuth 或 sampling。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `NAVI_HOME` | 替换默认的 `~/.navi-agent` 数据目录 |
| `NAVI_PROFILE` | 使用 `~/.navi-agent/profiles/<name>` 隔离 Profile |
| `NAVI_MODEL` | 模型名称 |
| `NAVI_API_KEY` | 模型 API Key |
| `NAVI_BASE_URL` | OpenAI 兼容接口的 Base URL |
| `NAVI_CONTEXT_LIMIT_TOKENS` | 上下文压缩使用的 Token 上限 |
| `NAVI_MAX_ITERATIONS` | 单次请求的最大迭代次数 |
| `NAVI_WEB_SEARCH_API_KEY` | Brave Search API Key |
| `NAVI_WEIXIN_TOKEN` | 微信网关 Token |
| `NAVI_WEIXIN_ACCOUNT_ID` | 微信网关账号 ID |
| `NAVI_WEIXIN_BASE_URL` | 微信网关 API 地址 |
| `NAVI_WEIXIN_POLL_INTERVAL_SECONDS` | 网关轮询间隔 |
| `NAVI_WEIXIN_DM_POLICY` | 私聊访问策略 |
| `NAVI_WEIXIN_ALLOWED_USERS` | 逗号分隔的允许用户 ID |
| `NAVI_LANGFUSE_ENABLED` | 启用 Langfuse 导出 |
| `LANGFUSE_PUBLIC_KEY` | Langfuse Public Key |
| `LANGFUSE_SECRET_KEY` | Langfuse Secret Key |
| `LANGFUSE_HOST` | Langfuse 服务地址 |

同时支持 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`BRAVE_SEARCH_API_KEY` 以及不带
`NAVI_` 前缀的微信环境变量作为回退值。

## 运行时数据

Navi Home 目录包含配置和持久化状态：

```text
~/.navi-agent/
├── config.yaml
├── state.db
├── pending-interactions.json
├── logs/
├── memories/
├── skills/
├── cron/
└── evolution/
```
