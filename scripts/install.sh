#!/bin/sh

set -eu

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "uv installation failed; see https://docs.astral.sh/uv/." >&2
    exit 1
fi

package="navi-agent"
if [ -n "${NAVI_AGENT_VERSION:-}" ]; then
    package="navi-agent==${NAVI_AGENT_VERSION}"
fi

echo "Installing ${package}..."
uv tool install --force "$package"

export PATH="$HOME/.local/bin:$PATH"
if command -v navi-agent >/dev/null 2>&1; then
    navi-agent --version
else
    echo "Installed successfully. Restart your shell, then run: navi-agent --version"
fi
