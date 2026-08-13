# Skill A/B 实际评测操作

本文使用 Anthropic 的 `internal-comms` Skill 和 3 个冻结的 Navi Agent 真实场景，
完成第一次可复现 A/B。它是小样本验证，不是完整 Benchmark。

## 实验回答什么问题

唯一变量是有没有候选 `internal-comms`：

```text
Baseline = 当前已激活的 Skill 集合
Variant  = 当前已激活的 Skill 集合 + internal-comms 候选
```

两边使用相同模型、System Prompt、工具、任务输入和冻结事实。导入只创建候选，
不会把 Skill 安装到正式运行环境；只有最后显式执行 `skill activate` 才会激活。

## 测试材料

- 外部 Skill 原件：
  `/Users/zoe/Devp/ai/llm/agent/anthropics-skills/skills/internal-comms`
- 本次评测使用的兼容副本：
  `/tmp/navi-internal-comms-eval-20260808/internal-comms`
- Case 文件：`evals/skill/internal_comms/cases.json`
- 场景数量：3
- 每个场景运行 Baseline 和 Variant 各一次
- 每轮总模型调用：6 次

三个场景分别测试：

1. 根据真实提交和当前问题编写 Navi Agent 3P 周报。
2. 根据已实现的 Skill 治理边界编写内部 FAQ。
3. 为项目负责人编写 Evolution 状态更新。

所有输入事实都已写入 Case，不依赖运行时读取 Git、GitHub 或网络，保证两组输入一致。

## 1. 准备环境

在 Navi Agent 仓库根目录执行：

```bash
cd /Users/zoe/Devp/ai/llm/agent/navi-agent
uv sync
uv run navi-agent doctor
```

确认当前正式 Skill Store 中没有 `internal-comms`：

```bash
uv run navi-agent --list-skills
```

如果列表中已经存在 `internal-comms`，本次 Baseline 也会包含它，实验就不再是
“无候选 vs 有候选”。此时不要继续，应改用一个没有激活该 Skill 的 Navi Home。

## 2. 准备兼容副本

Anthropic 原 Skill 把辅助规范放在 `examples/`；Navi 当前把可按需读取的文本资料放在
`references/`。不要修改外部仓库原件，复制一份并只调整资源目录名称和引用路径：

```bash
mkdir -p /tmp/navi-internal-comms-eval-20260808
cp -R \
  /Users/zoe/Devp/ai/llm/agent/anthropics-skills/skills/internal-comms \
  /tmp/navi-internal-comms-eval-20260808/internal-comms
mv \
  /tmp/navi-internal-comms-eval-20260808/internal-comms/examples \
  /tmp/navi-internal-comms-eval-20260808/internal-comms/references
sed -i '' \
  's#examples/#references/#g' \
  /tmp/navi-internal-comms-eval-20260808/internal-comms/SKILL.md
```

这个步骤不改变 Skill 的规则内容，也不修改 Navi 代码；它只把外部包适配为 Navi 已支持的
资源目录结构。可以检查引用是否已经更新：

```bash
rg -n 'references/' \
  /tmp/navi-internal-comms-eval-20260808/internal-comms/SKILL.md
```

## 3. 导入为候选

```bash
uv run navi-agent skill import \
  /tmp/navi-internal-comms-eval-20260808/internal-comms \
  --source-kind external
```

输出类似：

```text
skill_draft_id: 0123456789abcdef
skill_draft_status: candidate
```

复制 `skill_draft_id`。这一步相当于把 Skill 放入候选区供 Variant 使用，**不是正式
安装**。Baseline 看不到候选；评测器只会在 Variant 的临时 Skill Store 中加入它。

## 4. 运行 A/B

把上一条命令输出的 ID 填入变量：

```bash
DRAFT_ID=0123456789abcdef
uv run navi-agent skill eval "$DRAFT_ID" \
  --case-file evals/skill/internal_comms/cases.json
```

运行期间不要修改模型配置、Case 文件或正式 Skill Store。命令会按如下顺序执行：

```text
Case 1: Baseline → Variant
Case 2: Baseline → Variant
Case 3: Baseline → Variant
```

成功后会打印：

```text
skill_eval_report_path: ...
skill_eval_passed: yes|no
skill_eval_review_path: .../REVIEW.html
```

报告默认位于：

```text
~/.navi-agent/logs/evolution/skills/<timestamp>/
├── run.json
├── REPORT.md
└── REVIEW.html
```

## 5. 查看与记录人工判断

在 macOS 打开命令输出的完整路径：

```bash
open /完整路径/REVIEW.html
```

对每个场景选择 `Baseline`、`Variant` 或 `Tie`，并检查：

| 维度 | 判断标准 |
| --- | --- |
| 格式遵循 | 3P、FAQ、状态更新是否符合任务要求 |
| 事实准确 | 是否只使用 Case 中给出的冻结事实 |
| 信息分类 | 已完成、计划、风险是否放在正确位置 |
| 简洁程度 | 是否适合内部负责人快速阅读 |
| 不确定性 | 是否把未完成事项说成已经完成 |
| Skill 使用 | Variant 是否体现了对应的内部沟通规范 |

问题归因可优先使用：

- `skill_selection`：模型没有发现或加载候选 Skill。
- `instruction_quality`：Skill 已加载，但规范没有改善结果。
- `factuality`：输出虚构事实或错误表述完成状态。
- `completeness`：遗漏必要内容。

点击 `Download feedback.json` 保存人工反馈，然后将它绑定到本次评测证据：

```bash
uv run navi-agent skill feedback "$DRAFT_ID" \
  --report-path /完整路径/20260808-105810 \
  --feedback-file /完整路径/feedback.json
```

命令会校验 Draft、报告、Case 集合和人工评审场景是否一致，并保存不可变反馈证据。
它不会自动修改或激活 Skill；反馈仍然只作为后续问题归因和 Skill 修订的输入。

三轮实验均导入反馈后，查看只读聚合结论：

```bash
uv run navi-agent skill aggregate "$DRAFT_ID"
```

聚合仅比较 Skill 内容、Case 和模型配置指纹一致的实验。默认要求至少三轮、每轮机器
Gate 通过且每轮恰有一份人工反馈；结论为 `accepted`、`rejected` 或 `inconclusive`。
该结论不修改 Candidate，也不自动执行激活。

## 6. 解释机器结果

当前自动评分是最小确定性检查：

- Runtime 必须成功完成。
- Variant 必须包含每个 Case 的 `required_output_terms`。
- Variant 平均分不能低于 Baseline。

因此 `skill_eval_passed: yes` 只代表通过最低 Gate，**不代表 Skill 已被人工证明更好**。
如果两边都包含关键词，机器结果可能是 `unchanged`，仍需以 Viewer 中的内容比较为准。

第一次运行后，如果 Variant 看起来更好，建议使用同一个草稿再运行两次，观察模型随机性。
每次运行都会产生新的时间戳报告；3 轮合计 18 次模型调用。

建议的人工通过条件：

- 三个场景中至少两个选择 Variant。
- 没有场景出现 Variant 事实性退化。
- Variant 确实加载并遵循了 Skill，而不是偶然写得更长。
- 重复运行后结论基本一致。

## 7. 是否激活

只有机器 Gate 和人工评审都满意时才执行：

```bash
uv run navi-agent skill activate "$DRAFT_ID"
```

预期输出：

```text
skill_draft_status: promoted
```

随后确认：

```bash
uv run navi-agent --list-skills
```

此时 `internal-comms` 才正式出现在 Navi Agent 的活动 Skill Store。若人工结果不满意，
不要执行 `activate`；保留报告和 `feedback.json`，先修改 Skill，再创建新的候选进行下一轮。

## 已知限制

- 当前每个 Case 每个条件只执行一次，无法自动计算方差。
- 自动评分只检查关键词，不判断事实性、语气和内容质量。
- 人工反馈可显式导回 Evolution，但尚未自动聚合多轮实验或触发 Skill 修订。
- Baseline 可能受其他已激活 Skill 影响，因此评测前必须记录当前 Skill 列表。
- 激活命令目前不强制读取 `feedback.json`，人工 Gate 依靠操作者遵守。
