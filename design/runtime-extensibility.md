# Navi Agent Runtime Extensibility

## Decision

Navi Agent does not need a general-purpose plugin framework yet. It needs a
stable composition boundary between its runtime core and the capabilities
assembled around that core.

The target architecture borrows Pi's separation of a minimal agent loop, a
session-aware harness, composed resources, and an event stream. It deliberately
does not copy Pi's monorepo layout, dynamic extension loader, UI extension API,
or broad set of mutable lifecycle hooks.

The first implementation increment is limited to runtime resources and tool
providers:

- represent runtime-owned tools and cleanup callbacks explicitly;
- load built-in tools through a provider;
- load MCP tools through the same provider boundary;
- keep existing runtime, CLI, gateway, tool names, toolsets, and policies
  behavior-compatible.

## Current constraints

The existing architecture already has useful public boundaries:

- `ModelTransport` isolates model providers;
- `SessionStore` isolates conversation persistence;
- `ToolRegistry` and `ToolExecutor` isolate tool dispatch and policy;
- `RuntimeEventSubscriber` isolates trace and telemetry consumers;
- evolution reads persisted evidence and stays outside the online execution
  path.

The main extensibility constraints are orchestration boundaries rather than
missing modules:

1. `AgentRuntime._run_conversation()` owns session persistence, context,
   compaction, model calls, tool iteration, interaction suspension, events,
   traces, and result assembly.
2. `ApplicationService` combines online conversation use cases, session
   queries, interaction recovery, and evolution governance.
3. `build_runtime()` discovers MCP tools, creates all built-in tools, assembles
   stores and telemetry, creates subagent runtimes, and owns cleanup callbacks.
4. Adding a capability can therefore require coordinated edits to bootstrap,
   runtime, and a concrete capability module.

## Target architecture

```text
Weixin Gateway / CLI
          |
          v
  ConversationService
          |
          v
     AgentRuntime              compatibility facade
          |
    +-----+------+
    |            |
    v            v
AgentHarness   AgentLoop
session/run    model/tool
orchestration  state machine
    |
    +-- SessionStore
    +-- ContextPipeline
    +-- RuntimeResources
    +-- EventPublisher
             |
             +-- Trace
             +-- Telemetry
             +-- Run state

Evolution consumes persisted trace, event, and evaluation evidence only.
```

### AgentLoop

`AgentLoop` should eventually own only the model/tool iteration:

```text
messages -> model -> tool calls -> tool results -> model -> final response
```

It must not know about SQLite, skill files, memory files, gateways, evolution,
Langfuse, or background review.

### AgentHarness

The harness turns the loop into a usable session runtime. It owns session
loading and persistence, prompt and context construction, compaction, run
lifecycle, pending interactions, event publication, and usage aggregation.

`AgentRuntime` remains the public facade during migration so that CLI, gateway,
evaluation, and replay callers do not need to migrate together.

### RuntimeResources

Runtime capabilities are resolved during composition and passed to the runtime
as an explicit resource object. The online loop consumes resolved resources; it
does not discover MCP servers, read configuration, or construct stores.

The initial resource boundary contains:

```python
@dataclass(frozen=True, slots=True)
class RuntimeResources:
    tools: tuple[ToolRegistration, ...]
    close_callbacks: tuple[Callable[[], None], ...]
```

Prompt contributors and event subscribers may join this object in later,
independently reviewed increments after their behavior is proven.

## Initial extension points

### ToolProvider

A tool provider contributes tool registrations and owns any resources required
by those tools:

```python
class ToolProvider(Protocol):
    def load_tools(self) -> Sequence[ToolRegistration]: ...
    def close(self) -> None: ...
```

The first providers are:

- `BuiltinToolProvider`, for Navi's default tools and toolsets;
- `MCPToolProvider`, for configured stdio and Streamable HTTP MCP servers.

Provider failures, duplicate public names, source metadata, and cleanup must be
resolved before the agent loop begins. Cleanup remains idempotent and occurs in
reverse acquisition order.

### PromptContributor

This is the planned second extension point, not part of the first increment.
It will separate workspace, project context, memory, and skill-index prompt
sections from `PromptBuilder` while preserving the existing stable, context,
and volatile prompt boundaries.

### RuntimeEventSubscriber

The existing subscriber protocol remains the read-only observation boundary for
traces, telemetry, run state, usage, and audit consumers. Observers must not
mutate runtime state. Behavior-changing policies continue to use explicit
context, transport, or tool-policy interfaces.

## Application service direction

After the runtime boundary is stable, application use cases should be separated
into:

- `ConversationService`: handle, cancel, resume interaction, active run state;
- `SessionQueryService`: sessions, messages, traces, background tasks;
- `EvolutionService`: candidates, evaluation, review, promotion, rollback.

The current `ApplicationService` should remain temporarily as a thin facade over
those services. Evolution must continue to consume persisted evidence rather
than register behavior-changing hooks in the online runtime.

## Incremental delivery

### Increment 1: resource composition

1. Introduce explicit tool registrations, `ToolProvider`, and
   `RuntimeResources`.
2. Adapt default tools through `BuiltinToolProvider` without changing tool
   schemas, toolsets, approval, or policy behavior.
3. Adapt MCP discovery and cleanup through the provider boundary.
4. Make bootstrap assemble resources and give their lifecycle to the primary
   runtime.

Acceptance criteria:

- adding another tool source does not require editing the agent loop;
- built-in and MCP tool names, schemas, toolsets, and policy behavior remain
  unchanged;
- MCP startup remains failure-isolated and cleanup remains idempotent;
- duplicate tool names are rejected or reported during composition;
- subagents reuse resolved MCP tools without owning or closing MCP clients;
- relevant bootstrap, runtime, tools, and MCP tests pass.

### Increment 2: prompt composition

Introduce ordered prompt contributors for workspace, project context, memory,
and skill index. Preserve byte-for-byte prompt ordering where practical and
preserve provider-cache boundaries.

### Increment 3: loop extraction

Extract model/tool iteration from `AgentRuntime._run_conversation()` into an
`AgentLoop`. Preserve message order, tool-event order, trace payloads, usage,
cancellation, iteration limits, and interaction suspension.

### Increment 4: harness boundary

Move session, context, persistence, event lifecycle, and result assembly into a
session-aware harness. Keep `AgentRuntime` as the compatibility facade.

### Increment 5: application use cases

Split conversation, session-query, and evolution responsibilities behind the
existing `ApplicationService` interface.

## Explicit non-goals

The current plan does not introduce:

- separate Python distributions or a monorepo;
- dynamic plugin discovery or arbitrary code loading;
- hot reload;
- UI, command, keyboard, or gateway extension APIs;
- a generic mutable hook for every runtime event;
- a broad extension context with access to all application services;
- session tree or fork semantics.

These should be considered only after at least two real integrations cannot be
implemented cleanly through the narrow provider, contributor, transport,
policy, store, and event interfaces.

## Design guardrails

- Prefer typed protocols and explicit data objects over service locators.
- Snapshot composed resources before a run; do not mutate the tool universe in
  the middle of an iteration.
- Keep policy out of tools and resource providers.
- Keep discovery and configuration out of the agent loop.
- Give every acquired external resource one clear lifecycle owner.
- Preserve existing public interfaces during each extraction.
- Move files only when responsibility has changed; directory cleanup is not a
  goal by itself.
- Implement and verify one complete increment at a time.
