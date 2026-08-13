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

## Skill 候选项

导入人工编写或外部提供的 Skill 包，但不激活：

```bash
navi-agent skill import PATH --source-kind human
navi-agent skill import PATH --source-kind external
```

使用返回的草稿 ID 做 A/B 评测；通过 Gate 后再显式激活：

```bash
navi-agent skill eval DRAFT_ID --case-file cases.json
navi-agent skill feedback DRAFT_ID --report-path REPORT_DIR --feedback-file feedback.json
navi-agent skill activate DRAFT_ID
```

Case 文件使用刻意保持精简的格式：

```json
{
  "cases": [
    {
      "id": "review-readme",
      "prompt": "审查 README.md，并引用已验证的发现。",
      "required_output_terms": ["已验证"]
    }
  ]
}
```

评测产出 `run.json`、`REPORT.md` 和自包含的 `REVIEW.html`。Viewer 可以把人工判断
下载为 `feedback.json`，再通过 `skill feedback` 校验并保存为不可变评审证据；将反馈
自动送入修改循环不属于激活流程，当前刻意保持解耦。

可按照 [Skill A/B 实际评测操作](skill-evaluation.md)运行一个使用冻结 Navi Agent
场景的 `internal-comms` 完整实验。

## 本地 Trace Viewer

```bash
navi-agent trace serve
navi-agent trace render TRACE_ID
```

服务是只读的，并且只绑定 `127.0.0.1`。关于 Skill 字段、安全边界和单文件输出，
参见[本地 Trace Viewer](trace-viewer.md)。
