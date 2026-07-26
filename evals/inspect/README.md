# Inspect Evaluations

Inspect runs the production Navi Agent runtime and reads the model, API key, base
URL, tools, memory, skills, sessions, and telemetry settings from the normal Navi
configuration.

Run the 10-sample general QA evaluation:

```bash
navi-agent eval run general-qa
navi-agent eval run human-eval
```

`human-eval` executes generated Python and the official tests inside an Inspect
Docker sandbox. Docker must be running. The 10 static samples are selected from
OpenAI's MIT-licensed `openai/human-eval` test set.

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
