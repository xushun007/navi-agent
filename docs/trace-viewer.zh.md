# 本地 Trace Viewer

本地 Trace Viewer 是 Navi Runtime Session 的只读调试界面。它直接读取已有的
`traces.jsonl` 和 `runtime-events.jsonl`，不复制数据库，也不替代 Langfuse。

本地 Viewer 适合分析单次运行、查看真实 Model/Tool 顺序、确认 Skill 加载和离线排障；
Langfuse 继续负责远程聚合、成本分析与长期趋势。

## 启动 Viewer

```bash
uv run navi-agent trace serve
uv run navi-agent trace serve --port 9876 --limit 200
```

打开命令打印的地址，默认为 `http://127.0.0.1:8765`；使用 `Ctrl-C` 停止。

服务始终绑定 `127.0.0.1`，没有写入、删除、激活或 Replay 接口。HTTP 响应使用严格
CSP，页面渲染前也会遮蔽常见的凭证赋值内容。

## 渲染单条 Trace

不启动服务，直接生成一个自包含 HTML：

```bash
uv run navi-agent trace render TRACE_ID
uv run navi-agent trace render TRACE_ID --output /tmp/trace.html
```

默认输出目录为 `~/.navi-agent/logs/trace-viewer/`。

## Skill 字段

- **Available**：本次运行的 Skill 索引中可见的名称与描述。
- **Injected**：完整正文被预先注入 Prompt 的 Skill；渐进加载模式下通常为空。
- **Loaded**：运行中通过 `skill_view` 成功加载的 Skill。
- **Loaded references**：通过 `skill_view` 成功加载的附件文件。

时间线读取 Runtime Events，而不是 Langfuse 导出器当前分组后的 Model/Tool 数组，
因此能够保留 Model Response 与 Tool Execution 的真实交错顺序。

## 数据与限制

- Viewer 会向本机浏览器展示已记录的 Prompt、Reasoning、工具参数和结果；应把当前
  机器账号视为安全边界。
- 脱敏只是纵深防御，不能保证识别自由文本中的所有秘密。
- 服务会按请求读取 JSONL，适合本地开发数据，不适合大型多用户部署。
- Offline Replay 仍是独立 Runtime 服务，Viewer 当前不能执行 Replay。
