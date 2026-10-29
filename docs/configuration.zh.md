# 配置

Navi Agent 默认从 `~/.navi-agent/config.yaml` 读取 YAML 配置。环境变量的优先级高于配置文件。

默认模型为通过 DeepSeek 官方 OpenAI 兼容接口调用的 `deepseek-flash`；如需其他服务，使用
`NAVI_MODEL`、`NAVI_BASE_URL` 或配置文件中的对应字段覆盖。

## 配置文件

```yaml
model:
  name: deepseek-flash
  api_key: replace-with-your-api-key
  base_url: https://api.deepseek.com
  context_limit_tokens: 200000

runtime:
  max_iterations: 50

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

## 全局与项目指令

把跨项目使用的个人默认规则放在 `~/.navi-agent/AGENTS.md`，例如：

```markdown
# 全局指令
- 回答保持简洁。
- 修改代码后说明验证结果。
```

Navi 会把该文件作为 `[Global Instructions]` 加载在项目上下文之前，两者同时生效。
项目中非空的 `.navi.md` 优先于项目 `AGENTS.md`，但不会替代全局指令。
发生冲突时，当前用户请求优先于项目指令，项目指令优先于全局默认规则；
运行时安全和审批要求仍然适用。

全局文件跟随当前 Navi Home：设置 `NAVI_HOME` 时读取其中的 `AGENTS.md`；
使用 `NAVI_PROFILE` 时读取 `~/.navi-agent/profiles/<name>/AGENTS.md`，
不会同时加载默认 Home 中的文件。文件不存在或为空时跳过，每次对话请求重新读取。
超过 20,000 字符时截断并保留头尾；无法读取时报告提示词加载器错误。

## MCP 工具

MCP 支持本地 `stdio` 和远程 Streamable HTTP Server，并只接入其 Tools。先安装可选依赖：

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

    projects:
      type: http
      url: https://mcp.example.com/api
      headers:
        Authorization: "Bearer ${MCP_PROJECT_TOKEN}"
      startup_timeout_seconds: 10
      tool_timeout_seconds: 30
```

配置值中的 `${NAME}` 会在连接时从环境变量解析，实际值不会写入配置。远程地址
必须使用 HTTPS；只有 `localhost` 和回环地址允许 HTTP。发现的工具以
`mcp__files__工具名` 注册。某个 Server 启动失败时只禁用该 Server，不阻断 Navi
启动。当前不支持 resources、prompts、OAuth、sampling 或旧 SSE fallback。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `NAVI_HOME` | 替换默认的 `~/.navi-agent` 数据目录 |
| `NAVI_PROFILE` | 使用 `~/.navi-agent/profiles/<name>` 隔离 Profile |
| `NAVI_MODEL` | 模型名称 |
| `NAVI_API_KEY` | 模型 API Key |
| `DEEPSEEK_API_KEY` | DeepSeek API Key 回退值 |
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
├── AGENTS.md
├── config.yaml
├── state.db
├── pending-interactions.json
├── logs/
├── memories/
├── skills/
├── cron/
└── evolution/
```
