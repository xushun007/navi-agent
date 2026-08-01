# Sessions and Memory

Sessions and memory solve different problems:

- **Session state** is the authoritative conversation history for a user and
  session ID.
- **Memory** stores reusable user facts and preferences across sessions.

## Sessions

Navi Agent stores sessions in `state.db` under the active Navi home directory.
Interactive commands provide the common lifecycle:

```text
/new
/history
/resume <id>
/status
```

Session recall can search prior conversations and return relevant surrounding
messages. Resuming a session restores its persisted conversation state rather
than copying messages into a new session.

## Memory

Memory records live under `~/.navi-agent/memories/` and are scoped by user.
Recall separates stable profile information from query-relevant records before
adding them to runtime context.

The current workspace from the running application remains authoritative.
Historical memory must not override it with a stale path.

## Profiles

Use a profile to isolate sessions, memory, logs, and gateway state:

```bash
NAVI_PROFILE=work navi-agent
```

Use `NAVI_HOME` when the complete state directory must live elsewhere:

```bash
NAVI_HOME=/custom/navi-home navi-agent
```
