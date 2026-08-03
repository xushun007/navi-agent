from __future__ import annotations

from collections.abc import Mapping


_SECRET_ENV_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
_SECRET_ENV_NAMES = {
    "AWS_ACCESS_KEY_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "SSH_AUTH_SOCK",
}


def sanitized_subprocess_env(env: Mapping[str, str]) -> dict[str, str]:
    """Return a child-process environment without inherited credentials."""
    return {
        name: value
        for name, value in env.items()
        if name not in _SECRET_ENV_NAMES and not name.endswith(_SECRET_ENV_SUFFIXES)
    }
