# Navi Agent

一个参考 Hermes 思路、但只保留核心架构的自我进化 Agent 设计。

当前目标：

- 聚焦最小可行架构，不引入过多工程细节
- `gateway` 第一阶段只接入微信
- 强调 Agent 的“观察 -> 评估 -> 改进 -> 发布”闭环

## 1. 设计目标

这个项目不是先做一个“功能很多”的 Agent，而是先定义一个能持续自我进化的 Agent 内核。

核心关注点只有三个：

- `接入`：从微信接收用户消息与事件
- `执行`：完成理解、规划、工具调用与结果回复
- `进化`：基于运行日志、失败案例、人工反馈，持续优化自身策略

## 2. 核心架构

只保留 5 个核心模块。

```text
+-------------------+
| Weixin Gateway    |
| - webhook         |
| - message adapt   |
+---------+---------+
          |
          v
+-------------------+
| Agent Runtime     |
| - session         |
| - planner         |
| - executor        |
| - responder       |
+---------+---------+
          |
          v
+-------------------+
| Tool / Skill Bus  |
| - internal tools  |
| - external apis   |
+---------+---------+
          |
          v
+-------------------+
| Memory & Telemetry|
| - convo memory    |
| - traces/logs     |
| - feedback        |
+---------+---------+
          |
          v
+-------------------+
| Evolution Engine  |
| - eval            |
| - prompt policy   |
| - workflow update |
| - safe rollout    |
+-------------------+
```

## 3. 模块说明

### 3.1 Weixin Gateway

唯一入口，负责：

- 接收微信消息、事件、回调
- 完成签名校验、协议解析、统一消息格式
- 将微信数据适配为内部 `MessageEnvelope`
- 将 Agent 输出适配回微信回复格式

第一阶段明确不做：

- 多渠道统一网关
- 复杂流量调度
- 多租户隔离

### 3.2 Agent Runtime

这是运行时内核，负责一次请求的完整处理流程。

建议职责拆分为：

- `Session Manager`
  - 管理用户会话、上下文窗口、状态恢复
- `Planner`
  - 判断是直接回复，还是需要调用工具、执行任务
- `Executor`
  - 执行工具链、子任务、重试与错误恢复
- `Responder`
  - 组织最终回复，返回给微信网关

最小执行链路：

```text
用户消息
  -> Session 装载上下文
  -> Planner 生成行动方案
  -> Executor 执行工具或任务
  -> Responder 生成回复
  -> Weixin Gateway 回传微信
```

### 3.3 Tool / Skill Bus

这是 Agent 的动作层。

职责：

- 暴露统一工具调用接口
- 屏蔽具体外部 API、脚本、服务差异
- 为规划器提供可用能力清单

第一阶段建议只保留两类能力：

- `System Tools`
  - 搜索、读写配置、任务调度、内部函数
- `Domain Skills`
  - 面向具体业务场景的工作流封装

### 3.4 Memory & Telemetry

这是自我进化的数据基础。

至少保留三类数据：

- `Conversation Memory`
  - 用户画像、短期上下文、关键事实
- `Execution Trace`
  - 每次规划、工具调用、耗时、错误信息
- `Feedback Signal`
  - 用户显式反馈、人工标注、任务成功率

没有这层，进化就会退化成拍脑袋调 prompt。

### 3.5 Evolution Engine

这是区别于普通 Agent 的核心。

职责不是“自动改代码”，而是先做受控进化：

- 从运行数据中发现失败模式
- 评估当前策略、提示词、工作流的效果
- 生成候选改进项
- 在灰度环境中验证改进是否有效
- 通过后再发布到主运行链路

建议进化对象按风险从低到高分层：

1. `Prompt / Policy`
2. `Planner Rules`
3. `Tool Selection Strategy`
4. `Workflow Graph`
5. `Code / Plugin`

第一阶段只建议自动演进前 3 层。

## 4. 自我进化闭环

一个最小闭环如下：

```text
线上交互
  -> 采集 trace / feedback
  -> evaluator 定期评分
  -> 发现高频失败模式
  -> 生成候选策略改进
  -> 在 shadow / sandbox 中回放验证
  -> 通过后切换新版本策略
```

这里有两个关键原则：

- `先评估，后进化`
- `先进沙箱，后上线`

也就是说，运行时和进化引擎必须解耦，避免 Agent 直接在生产路径中无约束自改。

## 5. 推荐目录

当前只定义最小骨架，不预设复杂实现。

```text
navi-agent/
├── README.md
├── gateway/
│   └── weixin/
├── runtime/
│   ├── session/
│   ├── planner/
│   ├── executor/
│   └── responder/
├── tools/
├── memory/
├── telemetry/
├── evolution/
│   ├── evaluator/
│   ├── optimizer/
│   └── rollout/
└── docs/
```

## 6. 核心数据对象

建议优先统一这几个对象，而不是先写大量业务代码。

### 6.1 MessageEnvelope

```json
{
  "channel": "weixin",
  "user_id": "string",
  "session_id": "string",
  "message_id": "string",
  "timestamp": 0,
  "message_type": "text|event|image",
  "content": {},
  "metadata": {}
}
```

### 6.2 ExecutionTrace

```json
{
  "trace_id": "string",
  "session_id": "string",
  "input": {},
  "plan": {},
  "tool_calls": [],
  "result": {},
  "latency_ms": 0,
  "status": "success|failed",
  "error": null
}
```

### 6.3 EvolutionCandidate

```json
{
  "candidate_id": "string",
  "target": "prompt|planner_rule|tool_strategy",
  "baseline_version": "string",
  "proposal": {},
  "expected_gain": {},
  "evaluation_result": {},
  "rollout_status": "draft|tested|approved|rejected"
}
```

## 7. 第一阶段范围

为了把事情做实，第一阶段只做这些：

- 微信消息接入
- 单 Agent 运行时
- 基础工具调用机制
- 会话记忆与执行日志
- 基于日志回放的离线评估
- Prompt / Planner Rule 级别的受控优化

第一阶段不做这些：

- 多 Agent 社会化协作
- 自动改代码并直接上线
- 多渠道接入
- 复杂知识图谱
- 大规模自治任务市场

## 8. 演进路线

### Phase 1: 可运行

- 打通微信网关
- 完成最小 Runtime
- 接入基础 Telemetry

### Phase 2: 可评估

- 构建失败案例集
- 建立离线回放评测
- 对 Prompt / Planner 做版本化

### Phase 3: 可进化

- 自动生成候选优化
- 灰度验证策略改进
- 基于指标自动回滚

## 9. 项目原则

- 先做 `core loop`，不做大而全平台
- 先做 `controlled evolution`，不做无约束自修改
- 先统一对象模型，再扩工具和场景
- 先单入口微信，再扩展多渠道

## 10. 一句话定义

`Navi Agent = Weixin Gateway + Agent Runtime + Telemetry + Controlled Evolution`

这就是当前版本应该保留的核心。
