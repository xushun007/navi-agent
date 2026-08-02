# 权限

Navi Agent 将安全决策分为三层：

1. Tool Preflight 校验参数和工作区边界。
2. 运行时策略决定允许、拒绝或请求审批。
3. Approval Provider 在执行前记录用户决定。

## 默认行为

已知只读 Shell 命令可以无审批执行。存在副作用、后台执行或 Shell 结构不确定的命令会
请求审批。违反工作区策略的命令会被拒绝。

以下工具默认请求审批：

- `code_executor`
- `write_file`
- `patch`
- 被 Bash 策略判定为需要确认的命令

在交互会话中，审批框会提供 **Allow** 和 **Deny**。`/approve` 和 `/deny` 用于解决
会话交互流中的待处理请求。

## YOLO 模式

```bash
navi-agent --yolo
```

YOLO 模式会自动批准 `bash`、`code_executor`、`write_file` 和 `patch` 中支持的主机操作。

!!! warning "警告"
    `--yolo` 只改变审批行为，不会创建沙箱，也不会隔离主机进程。工作区路径检查仍然有效。

## 额外目录

使用显式目录授权，而不是放大默认工作区：

```bash
navi-agent --add-dir ../shared --add-dir /absolute/path/to/repo
```

每个路径在 CLI 启动时都必须已存在且为目录。
