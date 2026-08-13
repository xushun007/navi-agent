# Skill A/B Evaluation Walkthrough

This walkthrough evaluates Anthropic's `internal-comms` Skill on three frozen,
real Navi Agent communication scenarios. It is intentionally a small first
experiment, not a general benchmark.

See the [Chinese walkthrough](skill-evaluation.zh.md) for the complete operating
instructions used by this scenario.

The experiment keeps the model, prompt, tools, and active Skills fixed:

```text
Baseline = current active Skills
Variant  = current active Skills + internal-comms candidate
```

Before import, copy the external package and rename its `examples/` directory to
Navi's supported `references/` directory, updating the paths in `SKILL.md`. This
is a packaging adaptation and requires no Navi code change. Importing then
creates an inactive candidate. Only `skill activate` installs it into the active
Skill Store. The case file is
`evals/skill/internal_comms/cases.json`; one run executes three cases in both
conditions, for six model calls.

Machine scoring checks runtime success and required output terms. Review
`REVIEW.html` for factuality, concision, format adherence, and hallucinations
before making any activation decision. Export the review and bind it to its run:

```bash
navi-agent skill feedback "$DRAFT_ID" \
  --report-path /path/to/report \
  --feedback-file /path/to/feedback.json
```

The command validates the Draft, report, case set, and reviewed tasks before
persisting immutable feedback evidence. Human feedback remains advisory and is
not enforced by the activation command.
