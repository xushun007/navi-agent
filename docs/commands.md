# Slash Commands

Slash commands control an interactive Navi Agent session. Type `/help` to list
them in the terminal. Command names support completion in the input prompt.

| Command | Description |
| --- | --- |
| `/help` | Show available commands |
| `/new` | Start a new session |
| `/history` | Show recent sessions |
| `/resume <id>` | Resume an existing session and preview recent messages |
| `/status` | Show the current session status |
| `/tasks` | Show background tasks for the current session |
| `/steer <message>` | Redirect the active task without starting a second run |
| `/stop` | Stop the active task |
| `/approve` | Approve the pending tool request |
| `/deny` | Deny the pending tool request |
| `/exit` | Exit Navi Agent |

## Steering

Submitting a normal message while a task is active steers that task by default.
Use `/steer` when the intent should be explicit:

```text
/steer Focus only on the failing unit test.
```

Use `/stop` when the current run should terminate rather than change direction.

## Resume

`/history` lists recent session IDs. Resume one with:

```text
/resume 904a5fb048364abf91cfaf83f2d90cc7
```

Navi Agent switches the active session and displays a short history preview.
