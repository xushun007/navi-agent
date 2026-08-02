# Run Navi Agent in 2 Minutes

With Python, `uv`, and an OpenAI-compatible API key ready, the setup itself
takes about two minutes. The first package download may take longer depending
on your network.

## Before you start

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- An OpenAI-compatible model name, API key, and endpoint

## 1. Install

Install the latest version from GitHub:

```bash
uv tool install git+https://github.com/xushun007/navi-agent.git
```

## 2. Initialize

Create `~/.navi-agent/config.yaml`:

```bash
navi-agent init
```

## 3. Configure the model

Edit the generated configuration with your model credentials:

```yaml
model:
  name: gpt-4o-mini
  api_key: your-api-key
  base_url: https://api.openai.com/v1
```

Verify the configuration:

```bash
navi-agent doctor
```

## 4. Run

Start an interactive session in your project directory:

```bash
cd /path/to/your/project
navi-agent
```

Or run a single prompt:

```bash
navi-agent "Summarize this repository"
```

The startup directory is the authoritative workspace. To grant access to an
additional directory, add it explicitly:

```bash
navi-agent --add-dir ../shared
```

Multiple `--add-dir` options may be provided.

## Next steps

- Review the [CLI](cli.md) and [slash commands](commands.md).
- Understand [permissions](permissions.md) before using `--yolo`.
- Configure the [Weixin gateway](gateway.md) for remote access.
