# Permissions

Navi Agent separates three decisions:

1. Tool preflight validates arguments and workspace boundaries.
2. Runtime policy allows, denies, or requests approval.
3. The approval provider records the user's decision before execution.

## Default behavior

Known read-only shell commands can run without approval. Commands with side
effects, background execution, or uncertain shell structure request approval.
Commands that violate workspace policy are denied.

The following tools request approval by default:

- `code_executor`
- `write_file`
- `patch`
- Bash commands classified as requiring confirmation

In an interactive session, select **Allow** or **Deny** when the approval prompt
appears. `/approve` and `/deny` resolve a pending request exposed through the
session interaction flow.

## YOLO mode

```bash
navi-agent --yolo
```

YOLO mode auto-approves supported host operations for `bash`, `code_executor`,
`write_file`, and `patch`.

!!! warning
    `--yolo` changes approval behavior only. It does not create a sandbox or
    isolate processes from the host. Workspace path checks still apply.

## Additional directories

Grant external directories explicitly instead of broadening the default
workspace:

```bash
navi-agent --add-dir ../shared --add-dir /absolute/path/to/repo
```

Each path must exist and be a directory when the CLI starts.
