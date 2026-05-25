from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class ModelSettings:
    provider: str = "openai_compatible"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> "ModelSettings":
        return cls(
            provider=os.getenv("NAVI_MODEL_PROVIDER", "openai_compatible"),
            model=os.getenv("NAVI_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("NAVI_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("NAVI_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        )


@dataclass(slots=True)
class RuntimeSettings:
    max_iterations: int = 8

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        raw_value = os.getenv("NAVI_MAX_ITERATIONS", "8")
        return cls(max_iterations=int(raw_value))
