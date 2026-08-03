from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


_SECRET_ENV_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
_SECRET_ENV_NAMES = {
    "AWS_ACCESS_KEY_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "SSH_AUTH_SOCK",
}
_SECRET_FILE_NAMES = {
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pgpass",
    ".pypirc",
    "id_ed25519",
    "id_rsa",
}
_SECRET_DIR_NAMES = {".aws", ".gnupg", ".kube", ".ssh"}


def is_sensitive_path(path: Path) -> bool:
    """Return whether a resolved path commonly contains credentials."""
    name = path.name.lower()
    blocked_env = name == ".env" or (
        name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"}
    )
    return (
        blocked_env
        or name in _SECRET_FILE_NAMES
        or bool(_SECRET_DIR_NAMES.intersection(part.lower() for part in path.parts))
    )


def sanitized_subprocess_env(env: Mapping[str, str]) -> dict[str, str]:
    """Return a child-process environment without inherited credentials."""
    return {
        name: value
        for name, value in env.items()
        if name not in _SECRET_ENV_NAMES and not name.endswith(_SECRET_ENV_SUFFIXES)
    }
