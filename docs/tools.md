# Tools

The runtime exposes tools through a registry. Tools are grouped into toolsets,
while execution policy remains in the runtime layer.

| Toolset | Tools | Purpose |
| --- | --- | --- |
| `terminal` | `bash`, `background_task` | Run shell commands and inspect background processes |
| `code` | `code_executor` | Execute Python code in the workspace context |
| `file` | `read_file`, `glob`, `grep`, `write_file`, `patch` | Read, search, and edit files |
| `memory` | `memory` | Search and update persistent user memory |
| `session` | `session_search` | Recall relevant content from prior sessions |
| `scheduler` | `cron` | Manage scheduled jobs |
| `delegation` | `delegate_task` | Run bounded delegated tasks |
| `skills` | `skill_list`, `skill_view` | Discover and load governed skills |
| `todo` | `todo` | Track task progress |
| `web` | `web_search`, `web_fetch` | Search and fetch public web content |
| `interaction` | `ask_user` | Pause for structured user input |

Availability can depend on application assembly. For example, session,
delegation, skill, and interaction tools require their backing services.

## Workspace boundary

File and host tools start within the current workspace. Paths outside the
workspace are rejected unless their directory was granted with `--add-dir`.

```bash
navi-agent --add-dir /path/to/shared-repository
```

Preflight checks run before approval policy. This keeps invalid paths and tool
arguments from reaching execution.

## Concurrent execution

Independent read-only tool calls may execute concurrently. Calls that require
approval or depend on shared state remain sequential, and results preserve the
original tool-call order.
