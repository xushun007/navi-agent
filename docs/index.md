# Navi Agent

Navi Agent is a compact agent runtime for terminal and Weixin workflows. It
combines a model-driven runtime with workspace tools, persistent sessions,
memory, telemetry, and governed evolution.

## Start here

- [Install and run Navi Agent](getting-started.md)
- [Configure the model and runtime](configuration.md)
- [Understand tool permissions](permissions.md)
- [Connect the Weixin gateway](gateway.md)

## Core capabilities

| Area | What it provides |
| --- | --- |
| Runtime | Session-aware model and tool execution with steering and cancellation |
| Tools | Terminal, file, code, web, task, memory, and scheduling capabilities |
| Memory | Persistent user memory and searchable session history |
| Telemetry | Runtime events, traces, health summaries, and replay data |
| Gateway | Weixin protocol integration and direct-message access control |
| Evolution | Governed prompt and skill candidates, isolated from online execution |

Navi Agent uses the directory where the CLI starts as its workspace. Access to
other directories must be granted explicitly with `--add-dir`.
