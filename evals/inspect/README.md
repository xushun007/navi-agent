# Inspect Evaluations

Inspect runs the production Navi Agent runtime and reads the model, API key, base
URL, tools, memory, skills, sessions, and telemetry settings from the normal Navi
configuration.

Run the 10-sample general QA evaluation:

```bash
navi-agent eval run general-qa
navi-agent eval run human-eval
navi-agent eval run bfcl
navi-agent eval run agentbench-os
```

`human-eval` executes generated Python and the official tests inside an Inspect
Docker sandbox. Docker must be running. The 10 static samples are selected from
OpenAI's MIT-licensed `openai/human-eval` test set.

`bfcl` runs ten curated BFCL v4 function-calling cases through the real Navi
runtime. Each sample exposes only its benchmark functions as deterministic
tools. Scoring reads the resulting Navi tool trace and checks tool selection,
arguments, parallel calls, and irrelevant-tool refusal.

`agentbench-os` runs ten public-answer AgentBench OS dev tasks through Navi's
native file and terminal tools. Every sample gets a disposable workspace.
Answer tasks use exact matching; state-changing tasks additionally execute
deterministic checks against the final workspace.

The suite uses host-side disposable directories so Navi's production tools run
unchanged. It is not a process-security sandbox and should only be run with a
trusted model configuration.

For trusted local development only, Docker can be bypassed explicitly:

```bash
NAVI_EVAL_SANDBOX=local navi-agent eval run human-eval --limit 3
```

Local mode executes model-generated code on the host and is not isolated.

Run a subset:

```bash
navi-agent eval run general-qa --limit 5
navi-agent eval run general-qa --sample-id simpleqa-8
```

Inspect logs contain answer scores plus Navi runtime status, trace ID, iterations,
latency, token usage, and cost metadata for each sample. By default logs are
written to `~/.navi-agent/evals/inspect/`. The configured Navi model is also used
as the default grader.

## Current HumanEval Baseline

Run on 2026-07-26 with `deepseek-v4-pro` and the 10 curated samples:

| Metric | Result |
| --- | ---: |
| Functional correctness | 10/10 |
| Runtime success | 10/10 |
| Navi model calls | 10 |
| Navi tool calls | 0 |
| Runtime errors / approvals | 0 / 0 |
| Input / output tokens | 7,111 / 10,373 |
| P50 / P90 runtime latency | 12.4s / 25.1s |
| End-to-end duration | 2m39s |

Each sample completed in one runtime iteration. Inspect executed one isolated
Python test command per sample as the evaluator; those executions are not Navi
tool calls.

This is an L0 code-generation baseline, not a full HumanEval pass@1 result or an
autonomous coding-agent benchmark. The subset is public and intentionally small.

## Current BFCL Baseline

Run on 2026-07-26 with `deepseek-v4-pro` and the 10 curated samples:

| Metric | Result |
| --- | ---: |
| Tool-call correctness | 9/10 |
| Runtime success | 10/10 |
| Navi model calls / tool calls | 18 / 10 |
| Input / output tokens | 15,781 / 3,140 |
| P50 / P90 runtime latency | 7.2s / 8.8s |
| End-to-end duration | 1m14s |

Simple, multiple-choice, parallel-call, and irrelevant-tool cases all execute
through sample-specific deterministic tools. The failed case passed `x^2` where
the BFCL ground truth requires a canonical executable expression such as `x**2`.
