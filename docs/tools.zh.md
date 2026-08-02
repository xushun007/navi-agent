# 工具

运行时通过 Registry 暴露工具。工具被组织为 Toolset，执行策略仍属于运行时层。

| Toolset | 工具 | 作用 |
| --- | --- | --- |
| `terminal` | `bash`, `background_task` | 运行 Shell 命令并检查后台进程 |
| `code` | `code_executor` | 在工作区上下文中执行 Python 代码 |
| `file` | `read_file`, `glob`, `grep`, `write_file`, `patch` | 读取、搜索和修改文件 |
| `memory` | `memory` | 搜索和更新持久化用户记忆 |
| `session` | `session_search` | 从历史会话中召回相关内容 |
| `scheduler` | `cron` | 管理定时任务 |
| `delegation` | `delegate_task` | 执行边界明确的委派任务 |
| `skills` | `skill_list`, `skill_view` | 发现和加载受治理的 Skill |
| `todo` | `todo` | 跟踪任务进度 |
| `web` | `web_search`, `web_fetch` | 搜索和获取公开 Web 内容 |
| `interaction` | `ask_user` | 暂停并等待结构化用户输入 |

工具的可用性取决于应用组装。例如 Session、Delegation、Skill 和 Interaction 工具需要
对应的后端服务。

## 工作区边界

文件和主机工具默认在当前工作区中运行。工作区外的路径会被拒绝，除非使用
`--add-dir` 授权了对应目录。

```bash
navi-agent --add-dir /path/to/shared-repository
```

Preflight 检查在审批策略之前执行，防止无效路径和参数进入执行阶段。

## 并发执行

互相独立的只读工具调用可以并发执行。需要审批或依赖共享状态的调用保持串行，返回结果保留原始调用顺序。
