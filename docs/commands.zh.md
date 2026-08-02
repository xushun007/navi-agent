# Slash 命令

Slash 命令用于控制 Navi Agent 交互会话。在终端输入 `/help` 可查看命令列表，
输入框支持命令补全。

| 命令 | 说明 |
| --- | --- |
| `/help` | 显示可用命令 |
| `/new` | 开始新会话 |
| `/history` | 显示最近会话 |
| `/resume <id>` | 恢复已有会话并预览最近消息 |
| `/status` | 显示当前会话状态 |
| `/tasks` | 显示当前会话的后台任务 |
| `/steer <message>` | 调整正在运行的任务，不启动第二个 Run |
| `/stop` | 停止当前任务 |
| `/approve` | 批准待处理的工具请求 |
| `/deny` | 拒绝待处理的工具请求 |
| `/exit` | 退出 Navi Agent |

## Steering

当任务正在执行时，提交普通消息默认会 steer 该任务。如需显式表达意图：

```text
/steer 只关注失败的单元测试。
```

当任务应终止而不是改变方向时，使用 `/stop`。

## 恢复会话

`/history` 会列出最近的 Session ID。使用以下命令恢复：

```text
/resume 904a5fb048364abf91cfaf83f2d90cc7
```

Navi Agent 会切换当前会话，并展示一段简短的历史预览。
