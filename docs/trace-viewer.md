# Local Trace Viewer

The local Trace Viewer is a read-only debugging surface for Navi runtime
sessions. It reads the existing `traces.jsonl` and `runtime-events.jsonl`; it
does not copy telemetry into another database or replace Langfuse.

Use the local viewer for one-run diagnosis, true Model/Tool event order, Skill
loading, and offline investigation. Use Langfuse for remote aggregation, cost
analysis, and longer-term trends.

## Start the viewer

```bash
uv run navi-agent trace serve
uv run navi-agent trace serve --port 9876 --limit 200
```

Open the printed URL, normally `http://127.0.0.1:8765`. Stop the server with
`Ctrl-C`.

The server always binds to `127.0.0.1`. It has no write, delete, activation, or
Replay endpoint. Pages use a restrictive Content Security Policy and redact
common credential assignments before rendering stored content.

## Render one trace

Generate a self-contained HTML file without starting a server:

```bash
uv run navi-agent trace render TRACE_ID
uv run navi-agent trace render TRACE_ID --output /tmp/trace.html
```

The default output directory is `~/.navi-agent/logs/trace-viewer/`.

## Skill fields

- **Available**: Skill names and descriptions present in the run's Skill index.
- **Injected**: complete Skills preloaded into the prompt; normally empty with
  progressive Skill loading.
- **Loaded**: Skills successfully loaded through `skill_view`.
- **Loaded references**: attachment files successfully loaded through
  `skill_view`.

The event timeline comes from Runtime Events, not the grouped Model/Tool arrays
used by the current Langfuse exporter. It therefore preserves the actual
interleaving of model responses and tool execution.

## Data and limitations

- The viewer exposes locally recorded prompts, reasoning, tool arguments, and
  results to the local browser. Treat the machine account as the security
  boundary.
- Redaction is defense in depth, not a guarantee that arbitrary secrets in free
  text will be detected.
- The server reads JSONL on request and is intended for local development data,
  not large multi-user deployments.
- Offline Replay remains a separate runtime service and is not executable from
  the viewer.
