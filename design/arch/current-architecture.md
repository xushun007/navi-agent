# Navi Agent Current Architecture

This document captures the current Navi Agent architecture as of 2026-07-11.

## System View

```text
                         Navi Agent Current Architecture

┌─────────────────────────────────────────────────────────────────────┐
│                              Entry                                  │
├───────────────────────────────┬─────────────────────────────────────┤
│ Console CLI                   │ Weixin iLink Gateway                │
│ uv run navi-agent "..."       │ Local polling for text messages      │
└───────────────┬───────────────┴───────────────────┬─────────────────┘
                │                                   │
                └───────────────┬───────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ApplicationService                           │
│ - Unified application entry                                          │
│ - Binds user_id / session_id                                         │
│ - Calls Runtime                                                      │
│ - Proposes eval / skill candidates                                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            Runtime                                  │
│ AgentRuntime                                                        │
│ - PromptBuilder                                                      │
│ - ContextEngine / LLM summary compression                            │
│ - ModelTransport                                                     │
│ - ToolRegistry / ToolExecutor                                        │
│ - Approval / YOLO                                                    │
└───────────────┬───────────────────────┬─────────────────────────────┘
                │                       │
                ▼                       ▼
┌─────────────────────────────┐   ┌───────────────────────────────────┐
│            State            │   │              Tools                │
│ - SQLite session history    │   │ - read/search/write/patch          │
│ - JSONL runtime traces      │   │ - bash                             │
│ - File memory               │   │ - code_executor                    │
│ - File skills               │   │ - memory                           │
└───────────────┬─────────────┘   │ - todo                             │
                │                 └───────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           Evolution                                 │
│ - IFEval / Tool Use Eval / Smoke / Healthcheck                       │
│ - RuntimeTrace -> EvalCase candidate                                 │
│ - RuntimeTrace -> Skill candidate                                    │
│ - Human review                                                       │
│ - Prompt overlay                                                     │
│ - Skill apply -> ~/.navi-agent/skills                                │
│ - Skill usage status from traces                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Skill And Memory Loop

```text
User / Weixin
    │
    ▼
Runtime Conversation
    │
    ├── reads memory snapshot
    │       └── .navi-agent/memories/MEMORY.md
    │       └── .navi-agent/memories/USER.md
    │
    ├── retrieves relevant skills
    │       └── .navi-agent/skills/*/SKILL.md
    │
    ├── executes tools
    │       └── memory(action=add/list/update/remove)
    │
    └── writes trace
            └── .navi-agent/logs/traces.jsonl
                    │
                    ▼
              Evolution Engine
                    │
                    ├── skill candidate
                    │       └── uv run navi-agent --review-skill
                    │               └── accepted -> SKILL.md
                    │
                    └── eval candidate
                            └── human review / offline eval
```

## Data Layout

```text
.navi-agent/
├── state.db                         # SQLite session history
├── config.yaml                      # local config
├── logs/
│   ├── navi-agent.log               # app logs
│   └── traces.jsonl                 # runtime traces
├── memories/
│   ├── MEMORY.md                    # facts / tasks
│   └── USER.md                      # preferences
├── skills/
│   └── <skill-name>/
│       └── SKILL.md                 # reusable procedural memory
└── evolution/
    ├── candidates.jsonl             # eval / prompt / skill candidates
    ├── eval-cases.jsonl             # confirmed eval cases
    └── prompt-overlay.md            # applied prompt improvements
```

## Current State

- Entry is intentionally narrow: console and Weixin iLink text gateway.
- Runtime is the main execution path for session, context, LLM, tools, approval, and trace.
- Memory is now file-backed under `.navi-agent/memories`.
- Skills have a minimal closed loop: trace -> candidate -> human review -> `SKILL.md` -> runtime injection.
- Evolution is offline from the main serving path and uses traces, eval cases, candidates, and reports.
