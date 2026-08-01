# CLI

Run `navi-agent --help` for the complete option list. The commands below are
the stable entry points for normal operation.

## Agent sessions

```bash
navi-agent
navi-agent "Explain the runtime event flow"
navi-agent --session-id SESSION_ID
navi-agent --user-id USER_ID
```

| Option | Description |
| --- | --- |
| `--session-id ID` | Continue a specific session |
| `--user-id ID` | Select the local user identity; defaults to `local-user` |
| `--system-prompt TEXT` | Override the default system prompt |
| `--add-dir PATH` | Allow an additional workspace root; repeatable |
| `-y`, `--yolo` | Auto-approve supported host operations without adding isolation |

## Setup and diagnostics

```bash
navi-agent init
navi-agent doctor
navi-agent doctor --doctor-gateway weixin
```

## Gateway

```bash
navi-agent gateway start
navi-agent gateway send "Hello"
navi-agent gateway send "Hello" --to-user-id USER_ID
navi-agent gateway dead-letters
navi-agent gateway retry-dead-letter OUTBOX_ID
```

See [Gateway](gateway.md) for access policies and pairing.

## Scheduled tasks

```bash
navi-agent cron run
navi-agent cron start --cron-poll-interval 60
```

`cron run` performs one scheduler tick. `cron start` keeps polling until it is
stopped.

## Evaluations

Install optional evaluation dependencies, then run an Inspect suite:

```bash
uv sync --extra eval
uv run navi-agent eval run general-qa
uv run navi-agent eval run bfcl --limit 5
```

SWE-bench requires its dedicated extra:

```bash
uv sync --extra swe-bench
uv run navi-agent eval run swe-bench-verified --limit 1
```
