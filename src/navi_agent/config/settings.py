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


@dataclass(slots=True)
class WeixinGatewaySettings:
    token: str | None = None
    account_id: str | None = None
    base_url: str = "https://ilinkai.weixin.qq.com"
    poll_interval_seconds: float = 1.0
    dm_policy: str = "open"
    allowed_users: tuple[str, ...] = ()

    @classmethod
    def from_sources(cls, config: dict | None = None) -> "WeixinGatewaySettings":
        config = config or {}
        gateway_cfg = config.get("gateway") or {}
        weixin_cfg = gateway_cfg.get("weixin") or {}
        return cls(
            token=(
                os.getenv("NAVI_WEIXIN_TOKEN")
                or os.getenv("WEIXIN_TOKEN")
                or _optional_str(weixin_cfg.get("token"))
            ),
            account_id=(
                os.getenv("NAVI_WEIXIN_ACCOUNT_ID")
                or os.getenv("WEIXIN_ACCOUNT_ID")
                or _optional_str(weixin_cfg.get("account_id"))
            ),
            base_url=(
                os.getenv("NAVI_WEIXIN_BASE_URL")
                or os.getenv("WEIXIN_BASE_URL")
                or str(weixin_cfg.get("base_url", "https://ilinkai.weixin.qq.com"))
            ),
            poll_interval_seconds=float(
                os.getenv("NAVI_WEIXIN_POLL_INTERVAL_SECONDS")
                or str(weixin_cfg.get("poll_interval_seconds", "1.0"))
            ),
            dm_policy=(
                os.getenv("NAVI_WEIXIN_DM_POLICY")
                or os.getenv("WEIXIN_DM_POLICY")
                or str(weixin_cfg.get("dm_policy", "open"))
            ),
            allowed_users=_split_csv(
                os.getenv("NAVI_WEIXIN_ALLOWED_USERS")
                or os.getenv("WEIXIN_ALLOWED_USERS")
                or weixin_cfg.get("allowed_users")
                or ""
            ),
        )

    @classmethod
    def from_env(cls) -> "WeixinGatewaySettings":
        return cls.from_sources()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _split_csv(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


@dataclass(slots=True)
class LangfuseSettings:
    enabled: bool = False
    public_key: str | None = None
    secret_key: str | None = None
    host: str | None = None

    @classmethod
    def from_sources(cls, config: dict | None = None) -> "LangfuseSettings":
        config = config or {}
        telemetry_cfg = config.get("telemetry") or {}
        langfuse_cfg = telemetry_cfg.get("langfuse") or {}
        enabled = _as_bool(
            os.getenv("NAVI_LANGFUSE_ENABLED"),
            bool(langfuse_cfg.get("enabled", False)),
        )
        return cls(
            enabled=enabled,
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY") or _optional_str(langfuse_cfg.get("public_key")),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY") or _optional_str(langfuse_cfg.get("secret_key")),
            host=os.getenv("LANGFUSE_HOST") or _optional_str(langfuse_cfg.get("host")),
        )


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
