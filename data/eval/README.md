# Eval Seeds

This directory stores curated evaluation seed data.

- `ifeval_input_data.jsonl` is the raw export from IFEval.
- `ifeval_seed.jsonl` is the reviewed 5-sample seed set used for offline eval checks.

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
