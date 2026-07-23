from __future__ import annotations


def main() -> int:
    """Compatibility entry point for existing installed console scripts."""
    from .main import main as run

    return run()


__all__ = ["main"]
