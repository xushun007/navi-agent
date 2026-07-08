# Runtime Error Strategy

## Goal

Make `navi-agent` handle transient provider and transport failures with a small, explicit retry policy while keeping permanent failures fast and visible.

## Reference Direction

- Hermes treats provider errors as a retryable transport concern at the outer API-call boundary.
- Hermes classifies `429`, `5xx`, timeout, connection reset, and similar transport failures as transient.
- Hermes keeps permanent errors such as auth, bad input, and policy violations non-retryable.
- OpenCode keeps tool failures observable in session state and surfaces the error clearly to the loop.

## Scope

This design covers:

- model transport calls;
- gateway HTTP calls where retry is useful;
- error classification for runtime reporting;
- trace metadata for retry attempts.

This design does not try to invent a global error framework for the whole repo.

## Error Classes

### Retryable

Retryable errors are transient and should be retried with backoff:

- HTTP `429`;
- HTTP `5xx`;
- timeout;
- connection reset / aborted / refused;
- temporary network failures.

### Fatal

Fatal errors should fail fast:

- invalid arguments;
- malformed payloads;
- authentication failures;
- authorization failures;
- unsupported tool or protocol errors;
- developer bugs.

### Blocked

Blocked errors are intentional and must not be retried:

- approval denied;
- policy rejection;
- explicit safety stop.

## Policy

### Model transport

The OpenAI-compatible transport should:

- classify errors;
- retry only retryable errors;
- use bounded exponential backoff with jitter;
- stop after a small fixed attempt limit;
- preserve the last error for reporting.

### Gateway HTTP

Gateway HTTP calls should:

- retry retryable transport failures;
- avoid retrying permanent HTTP failures;
- back off on repeated failures;
- keep polling loops alive after transient faults.

### Tool execution

Tool execution should:

- keep returning structured tool failures;
- attach error type and status information when available;
- not retry arbitrary tool bugs inside the executor;
- let the runtime or tool itself decide whether a tool is retryable.

## Runtime Reporting

Each failed call should expose:

- `error_category` (`retryable`, `fatal`, `blocked`);
- `error_type`;
- `http_status` when available;
- `attempt_count`;
- `retryable` boolean;
- `final_error_message`.

The trace should keep retry metadata so offline evals can see whether failures were transient or real regressions.

## Unified Trace Contract

The same error shape should be used across runtime, gateway, and telemetry:

```text
error_category: retryable | fatal | blocked
error_type: str | None
error_message: str | None
retryable: bool | None
http_status: int | None
attempt_count: int
```

Rules:

- runtime records the final model or tool error with this shape;
- gateway records network failures with the same shape when it can classify them;
- telemetry should serialize the fields without interpretation;
- evaluators can rely on these fields for failure counting and regression checks.

## Implementation Plan

1. Add a small error classifier for transport-layer failures.
2. Wrap `OpenAICompatibleTransport.generate()` with bounded retry.
3. Add tests for `429`, `5xx`, and timeout classification.
4. Extend gateway HTTP calls only if the model transport work is stable.
5. Record retry metadata into trace and runtime events.

## Non-Goals

- no generalized circuit breaker;
- no multi-provider failover in this phase;
- no adaptive retry tuning;
- no speculative retry of tool logic.
