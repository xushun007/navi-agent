# 命令行

运行 `navi-agent --help` 可查看完整选项。以下是日常使用的稳定入口。

## Agent 会话

```bash
navi-agent
navi-agent "解释运行时事件流"
navi-agent --session-id SESSION_ID
navi-agent --user-id USER_ID
```

| 选项 | 说明 |
| --- | --- |
| `--session-id ID` | 继续指定会话 |
| `--user-id ID` | 选择本地用户标识，默认为 `local-user` |
| `--system-prompt TEXT` | 覆盖默认 System Prompt |
| `--add-dir PATH` | 授权额外工作区根目录，可重复传入 |
| `-y`, `--yolo` | 自动批准支持的主机操作，但不提供隔离 |

## 初始化与诊断

```bash
navi-agent init
navi-agent doctor
navi-agent doctor --doctor-gateway weixin
```

## 网关

```bash
navi-agent gateway start
navi-agent gateway send "Hello"
navi-agent gateway send "Hello" --to-user-id USER_ID
navi-agent gateway dead-letters
navi-agent gateway retry-dead-letter OUTBOX_ID
```

访问[网关](gateway.md)了解访问策略和配对流程。

## 定时任务

```bash
navi-agent cron run
navi-agent cron start --cron-poll-interval 60
```

`cron run` 执行一次调度器 Tick，`cron start` 持续轮询直到被停止。

## 评测

安装可选评测依赖，然后运行 Inspect Suite：

```bash
uv sync --extra eval
uv run navi-agent eval run general-qa
uv run navi-agent eval run bfcl --limit 5
```

SWE-bench 需要专用 Extra：

```bash
uv sync --extra swe-bench
uv run navi-agent eval run swe-bench-verified --limit 1
```
