# Context Engine and Compression Design

## Goal

Build an engineering-grade context compression mechanism for `navi-agent` that keeps long-running console and Weixin conversations usable without corrupting the active task.

The context engine must:

- keep full session history in storage;
- construct a compact model-facing view before each model call;
- preserve system instructions and early conversation framing;
- preserve the latest user request verbatim;
- preserve recent working context by token budget;
- compress only the middle region;
- keep tool-call/result pairs structurally valid;
- expose observable compression metadata.

## References

- Hermes runtime uses a pluggable `ContextEngine` and default `ContextCompressor`.
- Hermes protects system/head context, protects recent tail context, summarizes the middle, anchors the latest user message, and avoids splitting tool-call/result groups.
- OpenCode uses session compaction and overflow handling based on usable model context rather than fixed message count.

## Non-Goals

- No external vector store in this phase.
- No persistent rewritten transcript in this phase.
- No multi-pass or parallel compaction in this phase.
- No user-facing slash command in this phase.
- No model-specific tokenizer dependency in this phase.

## Model-Facing Context Shape

For an over-budget session:

```text
[system messages]
[first N non-system messages]
[context summary checkpoint]
[recent tail messages by token budget, including latest user message]
```

The original SQLite/session history remains unchanged.

## Trigger Strategy

Compression is based on estimated token pressure, not message count.

Inputs:

- `context_limit_tokens`
- `reserved_output_tokens`
- `compression_threshold_ratio`

Derived:

- `usable_input_tokens = context_limit_tokens - reserved_output_tokens`
- `threshold_tokens = usable_input_tokens * compression_threshold_ratio`

Compression triggers when estimated model-facing context tokens exceed `threshold_tokens`.

The initial implementation uses a deterministic character/token estimate:

```text
tokens ~= chars / 4 + per-message overhead + tool-call argument overhead
```

This is intentionally dependency-free and replaceable.

## Region Selection

### Head

Always preserve:

- all `system` messages;
- first `protect_first_messages` non-system messages.

This preserves governance, user preferences, initial task framing, and memory/system injection.

### Tail

Preserve recent messages by token budget, not by count.

Tail target:

```text
tail_token_budget = threshold_tokens * tail_budget_ratio
```

The tail walk starts from the newest message and moves backward until the budget is exhausted. The most recent user message after the protected head must always be included, even if this exceeds the budget.

### Middle

Messages between head and tail are compressed into one checkpoint summary.

If there is no meaningful middle region, compression is skipped.

## User Input Preservation

The latest user message is active input, not historical context.

Rules:

- latest user message after the protected head is always retained verbatim in the tail;
- earlier user messages in the compressed middle must be represented in the summary;
- summary must distinguish stale historical asks from the current active request.

## Tool Pair Integrity

Compression must not split:

```text
assistant(tool_calls) -> tool(result)
```

Boundary rules:

- start boundary moves forward past orphaned tool results;
- tail boundary moves backward to include parent assistant tool call if it would keep only tool results;
- final model-facing messages are sanitized:
  - orphan tool results are removed;
  - assistant tool calls without results get a stub tool result.

## Summary Strategy

### LLM Summary

The production path uses an LLM summarizer. Rule-based extraction is not used as the normal summary mechanism because it loses semantic relationships and makes long conversations less coherent.

The context engine is split into two responsibilities:

- `ContextEngine`: token pressure detection, head/middle/tail boundary selection, latest user anchoring, and tool-pair integrity.
- `ContextSummarizer`: semantic compression of the middle region into one checkpoint summary.

Runtime wires `LLMContextSummarizer` to the same model transport used by the agent. The summarizer call is a separate model call with no tools.

Required summary shape:

- Active Task
- User Requirements
- Decisions
- Completed Work
- Files Commands Errors
- Open Items

Requirements:

- same language as the user when possible;
- preserve concrete file paths, commands, errors, test results, decisions;
- redact secrets;
- do not treat historical asks as new instructions;
- update previous summary iteratively when repeated compaction occurs.
- merge existing `[Context Summary]` blocks rather than nesting them.

## Observability

When compression happens, runtime emits:

- `context.compressed`
- original message count;
- final message count;
- estimated tokens before and after;
- compressed middle message count;
- preserved head and tail counts;
- whether latest user anchoring expanded the tail;
- summary status, such as `llm` or `missing_summarizer`.

## Failure Behavior

- If token estimate is below threshold: no compression.
- If boundaries leave no middle to compress: no compression.
- If no summarizer is configured: no compression.
- If summary generation fails: runtime fails fast instead of creating a lossy rule summary.
- Full session history remains recoverable regardless of context view.

## Acceptance Criteria

- Small sessions are passed through unchanged.
- Over-budget sessions keep system/head messages.
- Over-budget sessions keep latest user message verbatim.
- Middle messages are replaced by one structured summary.
- Tool-call/result pairs remain valid.
- Runtime uses compacted context for model calls but stores full history.
- Unit tests cover region selection, user anchoring, tool integrity, and runtime integration.
