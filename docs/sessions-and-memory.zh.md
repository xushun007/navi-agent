# 会话与记忆

会话和记忆解决不同的问题：

- **会话状态**是用户和 Session ID 对应的权威对话历史。
- **记忆**用于跨会话保存可复用的用户事实和偏好。

## 会话

Navi Agent 将会话存储在当前 Navi Home 目录的 `state.db` 中。交互命令覆盖了常用生命周期：

```text
/new
/history
/resume <id>
/status
```

Session Recall 可搜索历史对话并返回相关上下文。恢复会话会加载已持久化的对话状态，
而不是将消息复制到新会话。

## 记忆

记忆记录位于 `~/.navi-agent/memories/`，并按用户隔离。Recall 先区分稳定的 Profile 信息与
当前查询相关的记录，再将它们加入运行时上下文。

当前运行应用的工作区是权威值。历史记忆不得用过期路径覆盖它。

## Profile

使用 Profile 隔离会话、记忆、日志和网关状态：

```bash
NAVI_PROFILE=work navi-agent
```

如需将完整状态目录放在其他位置，使用 `NAVI_HOME`：

```bash
NAVI_HOME=/custom/navi-home navi-agent
```
