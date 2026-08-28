# Configuration

Navi Agent reads YAML configuration from `~/.navi-agent/config.yaml` by
default. Environment variables override values from the file.

## Configuration file

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

## MCP tools

The first MCP integration supports local `stdio` servers and their tools only.
Install the optional dependency first:

```bash
uv sync --extra mcp
```

Then declare a server in the configuration:

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

Environment references must use the complete `${NAME}` form, so the actual value
does not need to be stored in the file. Discovered tools are registered as
`mcp__files__tool_name`. A broken server disables only that server and does not
prevent Navi from starting. Remote HTTP, resources, prompts, OAuth, and sampling
are not supported yet.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `NAVI_HOME` | Replace the default `~/.navi-agent` data directory |
| `NAVI_PROFILE` | Use `~/.navi-agent/profiles/<name>` as an isolated profile |
| `NAVI_MODEL` | Model name |
| `NAVI_API_KEY` | Model API key |
| `NAVI_BASE_URL` | OpenAI-compatible API base URL |
| `NAVI_CONTEXT_LIMIT_TOKENS` | Context window limit used by compaction |
| `NAVI_MAX_ITERATIONS` | Maximum runtime iterations per request |
| `NAVI_WEB_SEARCH_API_KEY` | Brave Search API key |
| `NAVI_WEIXIN_TOKEN` | Weixin gateway token |
| `NAVI_WEIXIN_ACCOUNT_ID` | Weixin gateway account ID |
| `NAVI_WEIXIN_BASE_URL` | Weixin gateway API endpoint |
| `NAVI_WEIXIN_POLL_INTERVAL_SECONDS` | Gateway polling interval |
| `NAVI_WEIXIN_DM_POLICY` | Direct-message access policy |
| `NAVI_WEIXIN_ALLOWED_USERS` | Comma-separated allowed user IDs |
| `NAVI_LANGFUSE_ENABLED` | Enable Langfuse export |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| `LANGFUSE_HOST` | Langfuse endpoint |

`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `BRAVE_SEARCH_API_KEY`, and the unprefixed
Weixin variables are also accepted as fallbacks.

## Runtime data

The Navi home directory contains configuration and persistent state:

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
