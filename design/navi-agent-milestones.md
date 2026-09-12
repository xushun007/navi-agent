# Navi Agent：从创建到当前的里程碑、设计与关键决策

> 状态基线：2026-09-12，`main` at `8c0b1e9`，共 451 个提交。

## 1. 这不是一份功能清单

Navi Agent 从一开始就没有把目标设为“再做一个功能最多的 Agent”。它要解决的是一个
更具体的问题：能否用尽可能小的代码和清晰的所有权，建立一条可以长期运行、可以解释、
可以恢复、也可以被验证后再进化的 Agent 执行链路。

项目最初受 Hermes 启发，保留了 Agent、工具、记忆、可观测性和进化组成的完整闭环；
后续又参考 Pi 对最小循环、资源组合和事件流的处理方式。但 Navi 没有照搬任何一个项目
的目录、插件系统或功能集合。它逐步形成了自己的约束：只保留解决当前真实问题所需要的
边界，并要求每个新能力能够进入同一条可靠执行链路。

今天的 Navi Agent 已经不再只是一个“模型调用工具”的循环。它是一个以
`AgentRuntime` 为中心，覆盖会话、上下文、工具、后台任务、事件、Trace、记忆、Skill、
评测和离线进化的紧凑型 Agent Runtime。

## 2. 主要里程碑

### 阶段一：建立最小闭环（2026-05-25—2026-05-29）

项目在 2026-05-25 创建。第一天完成的不是 UI，而是最小但完整的工程骨架：Python
Package、OpenAI-compatible Transport、Runtime、Tool Schema、Trace、Memory Store、
Evolution Store、Application Service 和 CLI。

随后几天补齐了 Toolset、工具执行策略、审批、结果渲染、Bash 安全校验和乐观文件写入。
这一阶段确定了最早的一条主线：

```text
用户输入 → Runtime → Model → Tool → Model → 最终响应
```

更重要的是，模型传输、工具能力、记忆和进化从一开始就是分开的模块，而不是后来从一个
巨大循环里重新拆出来。

代表提交：`9adb692`、`da9c741`、`54c0c65`、`6adc739`、`f7787ba`、`f7131ce`、
`4fe9308`、`0900c07`。

### 阶段二：让执行可以被观察和复现（2026-06-09—2026-06-20）

六月的重点从“能执行”转向“知道执行了什么”。内部 Trace Schema、Trace 查询、Replay
Service、序列化边界和 Langfuse Exporter 先后建立。Smoke Workflow 将多步任务与 Trace
关联，Evolution 开始从执行信号生成 Sample、Candidate、比较报告和 Review Summary。

这时形成了第一个进化闭环：线上执行产生证据，离线流程消费证据并形成候选；候选有状态、
来源和审查过程，而不是直接覆盖线上 Prompt。

这一阶段的关键价值不是“接入了 Langfuse”，而是 Navi 开始把执行事实当作可持久化、
可查询、可回放的数据。

代表提交：`ae20c94`、`2150d0f`、`fb76bf9`、`e94fe5a`、`6cc902e`、`a9c3d35`、
`259c5ce`、`8c9b579`。

### 阶段三：接入第一个真实 Gateway（2026-06-30—2026-07-08）

Navi 选择微信作为 Gateway 阶段唯一支持的协议。实现经历了 Skeleton、Webhook、iLink
Polling 的探索，最终主动删除 Webhook，收敛为更适合当前条件的 iLink 轮询链路，并加入
Pairing、允许列表、重试和错误标准化。

这里确立了 Gateway 的职责边界：Gateway 只处理协议、访问控制、消息适配和发送，不负责
规划、工具、记忆或回复生成。协议变化不应侵入 Runtime。

代表提交：`e381e2b`、`7c522cd`、`635fa87`、`1286f9d`、`afb69b0`、`a4d80e5`。

### 阶段四：上下文、记忆与 Skill 成为正式能力（2026-07-04—2026-07-19）

Context Compression 从简单裁剪演进为 LLM Summary，并进入 Smoke Check。Memory 从
简单 KV 能力演进为文件化 Markdown 记录，增加分类、更新、删除、注入限额、原子写入、
锁和 Prompt Injection 防护。

Skill 也在这一时期形成最小引擎：Skill Index 进入 Prompt，正文按需加载，运行记录会标注
可见、注入和实际加载的 Skill。Evolution 能从 Trace 提议 Skill Candidate，但 Skill 的
写入逐渐受到来源、证据窗口、Frontmatter 和 Review Agent 的约束。

两个重要原则在这里确立：

1. 长期记忆不是完整历史的另一份复制，而是经过治理的跨会话事实。
2. Skill 应渐进加载，先暴露索引，再按任务读取正文和附件，避免把全部知识塞入上下文。

代表提交：`4fd7a9b`、`516b9fe`、`a1462a9`、`e784755`、`419aa6c`、`79fc369`、
`dff82b2`、`f548d7f`、`a7410c0`、`cacab59`。

### 阶段五：从单轮循环走向可恢复 Runtime（2026-07-20—2026-07-25）

这是项目架构变化最大的一段时间。Append-only Runtime Event Stream 成为执行事实主线；
Tool Call、Model Delta、进度、健康状态和 Run State 都从事件派生。Trace 随后改为 Runtime
Events 的投影，而不再拥有另一套独立时序。

Runtime 同期获得后台任务、Cron、Subagent、并行任务、按 Session 调度、取消、Steer、
Pending Interaction 恢复、Tool Checkpoint、Run Lifecycle 和 Context Compression
Checkpoint。SQLite Session Store 增加并发和持久化加固，Session 保存来源、父子关系和
执行元数据。

这一阶段完成了性质上的转变：一次执行不再只是一个函数调用，而是一个有身份、有事件、
有检查点、可以中断和恢复的 Run。

代表提交：`4bd1e1a`、`8268503`、`02801ca`、`1406871`、`ae9c631`、`6945db7`、
`f08e17f`、`8164c40`、`9d72d74`、`41365c5`、`8cb27bf`、`8d5450a`、`4903427`、
`13b629b`。

### 阶段六：以评测和可靠性约束“自我进化”（2026-07-25—2026-08-05）

Offline Replay 被明确限制为无副作用执行；Skill 有不可变版本、评测证据、激活和归档
状态；Memory Mutation 和 Skill Promotion 都进入审计与治理边界。

七月底引入 Inspect 评测入口，并陆续接入 General QA、HumanEval、BFCL、AgentBench OS
和 SWE-bench Verified。它们通过 Navi 的真实 Application/Runtime 执行，而不是建立一套
与生产路径无关的 Eval Runtime。

八月初对两个高风险区域做了加固：

- 微信发送进入持久化 Delivery Loop，失败可进入 Dead Letter 并显式重试；Cron 结果和
  Background Task 状态可持久化，Shutdown Drain 有上限。
- Evolution 增加持久化 Gate、Promotion Gate 和 Change Provenance；未验证 Prompt 变更
  自动回滚，短暂信息不得写入 Durable Memory。

这时“自我进化”的定义被改写为：不是 Agent 可以修改自己，而是它可以提出变更，并用
可回放证据证明变更值得进入线上。

代表提交：`a5fe076`、`a9f05cd`、`699b782`、`97b9605`、`d50fd24`、`fab6fce`、
`2b450a8`、`eb79a03`、`3989a52`、`108dd3d`。

### 阶段七：Skill 生产与 Skill 评测正式解耦（2026-08-08—2026-08-17）

Skill 可以来自 Agent 自主生成、人工编写或外部项目。无论来源如何，都先进入 Candidate，
不会因为“导入成功”就自动激活。

评测侧建立了独立的 Skill A/B Harness：Baseline 使用当前激活集合，Variant 只额外加入
候选 Skill；两边共享模型、任务和冻结事实。静态 `REVIEW.html` 提供逐 Case A/B 对比，
人工可以选择 Baseline、Variant 或 Tie，标注问题归因并导回 `feedback.json`。多轮机器
与人工证据被聚合后，Activation Gate 才允许激活。

`internal-comms` 成为第一个真实场景：它验证了外部 Skill 的导入、隔离 A/B、机器 Gate、
人工 Review、反馈回流和激活链路，也暴露出脆弱字符串断言不能等同于任务质量的问题。

这一阶段同时增加了本地 Trace Viewer。Viewer 以 Session 和 Trace 为入口，展示真实
Model/Tool 交错、Skill 加载、Token Usage 和 Cost；它保持只读，不承担 Replay 或状态修改。

代表提交：`9efccf0`、`c750d92`、`513c19e`、`8830d61`、`a20cc48`、`5a4710f`、
`5b323c4`、`4712d10`、`8e01cad`、`a3dd5da`。

### 阶段八：用 MCP 扩展工具，而不是复制插件框架（2026-08-28—2026-08-29）

MCP 先支持本地 Stdio，再支持远程 Streamable HTTP。Server 配置、持久 Client、工具发现、
命名空间、调用适配和生命周期关闭逐步落地，并用真实 Stdio/HTTP Round Trip 验证。

Navi 只接入了当前真正需要的 MCP Tools，暂不支持 Resources、Prompts、OAuth、Sampling
和旧 SSE Fallback。这不是遗漏清单，而是一次明确的范围控制：先证明外部工具能够进入
现有 Tool Registry 和 Runtime，再由真实用例决定是否扩大协议面。

代表提交：`039d06f`、`993fe1e`、`c3b0bd1`、`47bd4ff`、`b1888b0`、`f797bca`、
`7f6738f`、`ee1cee6`、`30459a7`。

### 阶段九：扩展性重构与架构收口（2026-09-07—2026-09-12）

参考 Pi 后，Navi 没有引入通用 Plugin Framework，而是补齐几个小而稳定的组合点：

- `RuntimeResources` 显式持有工具、Prompt Contributor 和 Cleanup Callback。
- `ToolProvider` 统一 Builtin 与 MCP 的装配和生命周期。
- `PromptContributor` 拆分 Workspace、Memory、Skill Index 等 Prompt 来源。
- `ModelInvoker` 隔离模型调用。
- `AgentLoop` 只负责 Model/Tool 迭代状态机。
- `AgentProfile` 描述 Primary Agent 和 Subagent 的已解析执行选择。
- Application 层拆为 Conversation、Session Query 和 Evolution 用例服务。

最关键的决定不是“又拆出了几个类”，而是停止继续拆：团队否决了额外的
`AgentHarness`。`AgentRuntime` 保持一次会话执行的唯一编排者，负责 Session、Context、
Compaction、Run Lifecycle、Interaction、Event 和 Result；`AgentLoop` 只负责循环。

这避免了 `AgentRuntime`、`AgentHarness` 和 `AgentLoop` 三层概念互相争夺所有权，也使
“Agent Runtime”继续成为对外清晰、符合行业语义的核心概念。

代表提交：`44bbc03`、`a4aa63a`、`e109cdb`、`458a696`、`5d23502`、`e0fc8aa`、
`97df104`、`ae20753`、`b846d3d`、`1edafc6`、`b01adf6`、`a9e34ac`。

## 3. 当前核心架构

```text
Weixin Gateway / CLI
          |
          v
 Application Services
          |
          v
     AgentRuntime
  session/run orchestration
          |
    +-----+--------------------+
    |                          |
    v                          v
 AgentLoop              Runtime dependencies
 model/tool              SessionStore
 state machine           ContextEngine
                         RuntimeResources
                         EventPublisher
                              |
                              +-- Event Store
                              +-- Trace / Usage
                              +-- Local Viewer / Langfuse

Evolution consumes persisted execution and evaluation evidence offline.
```

各层的所有权已经比较明确：

- Gateway：协议、身份和消息适配。
- Application Services：面向 CLI/Gateway 的用例入口。
- AgentRuntime：一次会话 Run 的完整编排。
- AgentLoop：纯 Model/Tool 迭代。
- Tools：能力与 Schema，不拥有审批策略。
- Session Store：对话历史的权威来源。
- Memory：经过治理的跨会话事实。
- Runtime Events：执行事实流。
- Trace/Viewer/Langfuse：事实流的不同观察投影。
- Evolution：离线消费证据，不能旁路线上 Runtime。

## 4. 最重要的设计与关键决策

### 4.1 保持最小闭环，而不是追求功能覆盖率

Navi 的核心始终限定为 Gateway、Runtime、Tools、Memory/Telemetry 和 Evolution。
Gateway 阶段只支持微信；MCP 阶段只支持 Tools；扩展性阶段不做动态插件加载。每一次限制
都减少了尚未被真实问题证明的复杂度。

### 4.2 Runtime 是所有者，Loop 是机制

`AgentLoop` 可以很小，因为它只表达迭代机制；真正让 Agent 可用的是 `AgentRuntime`
拥有的 Session、Context、Persistence、Cancellation、Checkpoint、Event 和 Result。
Navi 不用 Loop 的代码行数定义 Agent，也不增加另一个 Harness 稀释 Runtime 的语义。

### 4.3 Event Stream 是一级架构，不是日志格式

Run State、Trace、UI Progress、Tool Trajectory 和 Health 从同一条 Runtime Event Stream
派生。这样线上执行只产生一次事实，不同消费者各自投影，避免日志、Trace 和 UI 对同一
次执行给出不同顺序。

### 4.4 状态必须有唯一权威来源

Session History 由 Session Store 拥有；当前 Workspace 由本次运行拥有；Runtime Event
由 Event Store 拥有；Skill Version 和 Eval Evidence 不可变。Trace 不复制完整历史，
Memory 也不能覆盖当前运行事实。这些约束比增加更多 Recall 算法更重要。

### 4.5 Context 压缩必须可检查和可恢复

压缩不是静默删除旧消息。Navi 保存 Compression Checkpoint，记录 Summary Model Call，
并在每个 Run 重新构造动态上下文。出现问题时能够知道模型看到了什么、何时发生压缩。

### 4.6 Tool 提供能力，Policy 决定能否执行

Tool 自己负责输入和能力实现；Tool Registry、Executor、Approval Provider 和 Command
Policy 负责风险分类、审批、并发和恢复。MCP Provider 也只是贡献工具，不能绕过同一套
执行策略。

### 4.7 Evolution 必须与线上执行解耦

Evolution 不注册可以改变 Runtime 行为的事件 Hook，也不会观察到一个失败就立刻改写
线上 Prompt 或 Skill。它读取持久证据、提出 Candidate、运行 Eval、接受 Review，再由
Promotion Gate 改变激活状态。

### 4.8 Skill 生产、评测和激活是三个职责

Skill 来源不决定质量。自主生成、人工编写和外部提供的 Skill 都走 Candidate；A/B Harness
对所有来源使用同一套隔离评测；Activation 是最后的治理动作。这使“生成能力”与“证明
能力”可以独立演进。

### 4.9 本地 Review 需要全息证据，但必须保持只读

本地 Viewer 补足了远程 Trace 平台不适合逐条人工比较的问题。它展示真实时序、参数、
结果、Skill 和 Usage，但不提供修改、Replay 或 Promotion API。观察面不能偷偷成为另一条
控制面。

### 4.10 扩展通过组合点进入，不通过全能插件上下文进入

新能力优先选择 `Profile`、`Provider`、`Contributor`、`Transport`、`Store`、`Policy` 或
`Event Subscriber`。Navi 明确拒绝一个能访问所有服务、在任意生命周期修改状态的插件
上下文。只有至少两个真实集成无法通过现有窄接口实现时，才重新讨论更大的扩展框架。

### 4.11 ApplicationService 可以兼容，但不能成为上帝对象

对外保留 `ApplicationService` 以避免 CLI、Gateway 和 Eval 同时迁移；内部则把 Conversation、
Session Query 和 Evolution 用例拆开。Facade 是兼容边界，不再是所有业务逻辑的归宿。

### 4.12 每个可靠性问题都优先补状态，而不是补重试次数

微信发送、Cron、Background Task、Tool Execution、Context Compression 和 Evolution
Promotion 的改进有一个共同方向：先让状态可持久化、可识别、可恢复，再讨论自动重试。
没有状态所有权的重试只会把“偶尔失败”变成“偶尔重复执行”。

## 5. Navi 保留了什么，又拒绝复制什么

Navi 从 Hermes 保留了完整 Agent 工程闭环和“运行产生进化证据”的方向；从 Pi 保留了
最小 Loop、资源组合、事件流和清晰 Session Runtime 的启发。

它拒绝复制的部分同样重要：

- 不因参考项目采用 Monorepo 就拆成多个 Package。
- 不因扩展需求存在就提前构建动态 Plugin Loader。
- 不提供可以修改所有 Runtime 状态的通用 Hook。
- 不把 UI、Command、Gateway 和 Tool 全部塞进同一个扩展协议。
- 不因为 `AgentRuntime` 较大就机械增加 `AgentHarness` 包装层。
- 不把 Evolution 接入线上热路径。
- 不把导入 Skill 等同于安装和激活。

这些拒绝共同保护了 Navi 的 KISS 原则：扩展性来自稳定的职责边界，而不是抽象数量。

## 6. 当前状态

截至 2026-09-12，Navi 已经具备：

- 可交互 CLI 与微信 iLink Gateway；
- Streaming、Tool Concurrency、Background Task、Cron 和 Subagent；
- SQLite Session、Run/Tool/Compression Checkpoint 和跨 Session Recall；
- 文件化 Durable Memory 和渐进加载 Skill；
- Append-only Runtime Events、Trace、Usage、Langfuse 和本地只读 Viewer；
- Offline Replay、Inspect Eval Suites 和 Skill A/B Review；
- 受 Promotion Gate 约束的 Prompt、Memory 和 Skill Evolution；
- MCP Stdio 与 Streamable HTTP Tools；
- `AgentRuntime → AgentLoop` 与 Profile/Provider/Contributor 组成的扩展边界。

架构性重构已经收口。当前最大的风险不再是“缺少一个抽象”，而是已有能力是否经过足够
长时间、足够多真实任务和故障场景的验证。

仍然明确存在的边界包括：

- 微信、Cron、后台任务和恢复链路仍需长期运行验证；
- Skill 自动评分仍无法替代事实性、表达质量和任务适配度的人工判断；
- Eval 覆盖面与真实用户任务分布仍需持续校准；
- MCP 当前只接入 Tools，其他协议能力需要真实需求证明；
- 本地 Viewer 是开发者工具，不是多用户观测平台；
- 更大的插件系统、Session Fork 和多 Gateway 都不是当前目标。

## 7. 下一阶段应该如何判断优先级

下一阶段不应继续以“参考项目还有什么”为路线图，而应以证据排序：

1. **先验证可靠性**：让微信、后台任务、Cron、取消和恢复经历长时间真实运行。
2. **再验证任务表现**：用真实任务数据扩展 Eval，观察 Tool、Memory 和 Skill 是否真的提高
   完成率，而不是只提高系统复杂度。
3. **提高 Evolution 证据质量**：减少脆弱字符串 Gate，增加事实性、回归和多轮稳定性判断。
4. **用真实扩展检验架构**：新能力先通过现有组合点实现；只有具体阻力重复出现，才调整
   `AgentRuntime` 或扩展协议。
5. **继续克制协议面**：MCP Resources、Prompts、OAuth、Sampling 或新 Gateway 应由明确
   场景拉动，而不是为了对齐其他 Agent 的功能表。

Navi Agent 到当前最重要的成果，不是已经拥有多少功能，而是逐渐建立了一套判断标准：
执行事实必须可观察，状态必须有唯一所有者，失败必须可恢复，进化必须有证据，扩展必须
通过窄边界，而任何新抽象都必须先证明自己解决了一个真实问题。
