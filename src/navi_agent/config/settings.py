from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from navi_agent.paths import get_config_path
import yaml


def load_config(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path is not None else get_config_path()
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


@dataclass(slots=True)
class ModelSettings:
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None

    @classmethod
    def from_sources(cls, config: dict | None = None) -> "ModelSettings":
        config = config or {}
        model_cfg = config.get("model") or {}
        return cls(
            model=os.getenv(
                "NAVI_MODEL",
                str(model_cfg.get("name", "gpt-4o-mini")),
            ),
            api_key=(
                os.getenv("NAVI_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or _optional_str(model_cfg.get("api_key"))
            ),
            base_url=(
                os.getenv("NAVI_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or _optional_str(model_cfg.get("base_url"))
            ),
        )

    @classmethod
    def from_env(cls) -> "ModelSettings":
        return cls.from_sources()


@dataclass(slots=True)
class RuntimeSettings:
    max_iterations: int = 8

    @classmethod
    def from_sources(cls, config: dict | None = None) -> "RuntimeSettings":
        config = config or {}
        runtime_cfg = config.get("runtime") or {}
        raw_value = os.getenv(
            "NAVI_MAX_ITERATIONS",
            str(runtime_cfg.get("max_iterations", "8")),
        )
        return cls(max_iterations=int(raw_value))

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls.from_sources()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
