# Inspect Evaluations

Inspect runs Navi Agent through its native `AgentRuntime`. The Agent Bridge routes
model requests to the model selected by Inspect while Navi keeps ownership of the
runtime loop and trace metadata.

Run the 10-sample general QA evaluation:

```bash
uv run python -m inspect_ai eval evals/inspect/general_qa.py \
  --model openai/<agent-model> \
  --model-role grader=openai/<grader-model>
```

Use `mockllm/model` for a dependency-free pipeline smoke test:

```bash
uv run python -m inspect_ai eval evals/inspect/general_qa.py \
  --model mockllm/model \
  --model-role grader=mockllm/model
```

Inspect logs contain answer scores plus Navi runtime status, trace ID, iterations,
latency, token usage, and cost metadata for each sample.
