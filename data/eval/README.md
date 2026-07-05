# Eval Seeds

This directory stores curated evaluation seed data.

- `ifeval_input_data.jsonl` is the raw export from IFEval.
- `ifeval_seed.jsonl` is the reviewed 5-sample seed set used for offline eval checks.
- `tool_use_seed.jsonl` is a benchmark-inspired seed set for Navi tool-use evals.

Format:

```json
{
  "key": 1001,
  "prompt": "...",
  "instruction_id_list": ["..."],
  "kwargs": [{}],
  "session_id": "ifeval-002",
  "output": "...",
  "pass_fail": true,
  "notes": "..."
}
```

Keep design material under `design/`; keep usable evaluation assets here.

## Tool Use Seed Format

Tool-use cases share one schema across levels:

- `L0`: tool selection and arguments.
- `L1`: multi-step tool execution and approval boundaries.
- `L2`: environment/state validation.

The seed cases are not copied benchmark items. They are Navi-specific tasks inspired by BFCL, API-Bank, ToolBench, and tau-bench design patterns.
