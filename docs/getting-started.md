# Getting Started

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- An OpenAI-compatible model endpoint

## Install

Install the latest version from GitHub:

```bash
uv tool install git+https://github.com/xushun007/navi-agent.git
```

For development, clone the repository and synchronize its dependencies:

```bash
git clone https://github.com/xushun007/navi-agent.git
cd navi-agent
uv sync
```

## Initialize

Create the default configuration file and verify it:

```bash
navi-agent init
navi-agent doctor
```

Edit `~/.navi-agent/config.yaml` and provide a model name and API key before
starting an interactive session.

## Run

Start Navi Agent in the current directory:

```bash
navi-agent
```

Run a single prompt:

```bash
navi-agent "Summarize this repository"
```

The startup directory is the authoritative workspace. To grant access to
another directory, add it explicitly:

```bash
navi-agent --add-dir ../shared
```

Multiple `--add-dir` options may be provided.

## Build the documentation

From a development checkout:

```bash
uv run --group docs mkdocs serve
```

Run a strict production build before committing documentation changes:

```bash
uv run --group docs mkdocs build --strict
```

## Next steps

- Review the [CLI](cli.md) and [slash commands](commands.md).
- Understand [permissions](permissions.md) before using `--yolo`.
- Configure the [Weixin gateway](gateway.md) for remote access.
