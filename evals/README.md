# Evaluations

`evals/` contains external evaluation tasks and adapters. Evaluation frameworks
own datasets, scoring, and reports; Navi Agent continues to own application
configuration and runtime execution.

## Inspect

Inspect is an optional evaluation dependency. Install the base evaluation
environment before running the lightweight suites:

```bash
uv sync --extra eval
```

The suites use Navi's configured model and real Runtime/Trace contract.
General QA and HumanEval use the production application assembly. Tool-heavy
suites use isolated stores and suite-specific tools so benchmark side effects
remain inside their evaluation environments.

```bash
# Run all 10 general QA samples
navi-agent eval run general-qa

# Run a subset
navi-agent eval run general-qa --limit 5
navi-agent eval run general-qa --sample-id simpleqa-8

# Run 10 curated HumanEval coding problems
navi-agent eval run human-eval
navi-agent eval run human-eval --sample-id HumanEval/0

# Run the 15-instance SWE-bench Verified suite
uv sync --extra swe-bench
navi-agent eval run swe-bench-verified
navi-agent eval run swe-bench-verified \
  --sample-id astropy__astropy-12907
```

The command reads the normal Navi configuration from
`~/.navi-agent/config.yaml`. Results are written to
`~/.navi-agent/evals/inspect/` by default.

```bash
inspect view --log-dir ~/.navi-agent/evals/inspect
```

See `evals/inspect/README.md` for Inspect-specific details.
