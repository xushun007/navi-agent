from __future__ import annotations

import os
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

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
    context_limit_tokens: int = 128_000

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
            context_limit_tokens=int(
                os.getenv(
                    "NAVI_CONTEXT_LIMIT_TOKENS",
                    str(model_cfg.get("context_limit_tokens", "128000")),
                )
            ),
        )

    @classmethod
    def from_env(cls) -> "ModelSettings":
        return cls.from_sources()


@dataclass(slots=True)
class RuntimeSettings:
    max_iterations: int = 30

    @classmethod
    def from_sources(cls, config: dict | None = None) -> "RuntimeSettings":
        config = config or {}
        runtime_cfg = config.get("runtime") or {}
        raw_value = os.getenv(
            "NAVI_MAX_ITERATIONS",
            str(runtime_cfg.get("max_iterations", "30")),
        )
        return cls(max_iterations=int(raw_value))

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls.from_sources()


@dataclass(slots=True)
class WebSettings:
    search_api_key: str | None = None

    @classmethod
    def from_sources(cls, config: dict | None = None) -> "WebSettings":
        config = config or {}
        web_cfg = config.get("web") or {}
        return cls(
            search_api_key=(
                os.getenv("NAVI_WEB_SEARCH_API_KEY")
                or os.getenv("BRAVE_SEARCH_API_KEY")
                or _optional_str(web_cfg.get("search_api_key"))
            )
        )

    @classmethod
    def from_env(cls) -> "WebSettings":
        return cls.from_sources()


@dataclass(frozen=True, slots=True)
class MCPServerSettings:
    name: str
    transport: str = "stdio"
    command: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    startup_timeout_seconds: float = 10.0
    tool_timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class MCPSettings:
    servers: tuple[MCPServerSettings, ...] = ()

    @classmethod
    def from_sources(cls, config: dict | None = None) -> "MCPSettings":
        config = config or {}
        mcp_cfg = config.get("mcp") or {}
        raw_servers = mcp_cfg.get("servers") or {}
        if not isinstance(raw_servers, dict):
            raise ValueError("mcp.servers must be an object")

        servers = []
        for name, value in raw_servers.items():
            if not isinstance(value, dict):
                raise ValueError(f"mcp server {name!r} must be an object")
            if not _as_bool(value.get("enabled"), True):
                continue
            server_name = str(name).strip()
            transport = str(value.get("type") or "stdio").strip().lower()
            if not server_name or transport not in {"stdio", "http"}:
                raise ValueError(f"mcp server {name!r} has an invalid name or type")
            command = value.get("command") or []
            if transport == "stdio" and (not isinstance(command, list) or not command):
                raise ValueError(f"mcp server {name!r} requires a command list")
            arguments = tuple(str(item).strip() for item in command)
            if any(not item for item in arguments):
                raise ValueError(f"mcp server {name!r} has an invalid command")
            environment = value.get("environment") or {}
            if not isinstance(environment, dict):
                raise ValueError(f"mcp server {name!r} environment must be an object")
            url = str(value.get("url") or "").strip()
            if transport == "http" and not url:
                raise ValueError(f"mcp server {name!r} requires a url")
            if transport == "http":
                _validate_mcp_http_url(server_name, url)
            headers = value.get("headers") or {}
            if not isinstance(headers, dict):
                raise ValueError(f"mcp server {name!r} headers must be an object")
            servers.append(
                MCPServerSettings(
                    name=server_name,
                    transport=transport,
                    command=arguments,
                    environment={str(key): str(item) for key, item in environment.items()},
                    url=url,
                    headers={str(key): str(item) for key, item in headers.items()},
                    startup_timeout_seconds=float(
                        value.get("startup_timeout_seconds", 10.0)
                    ),
                    tool_timeout_seconds=float(value.get("tool_timeout_seconds", 30.0)),
                )
            )
        return cls(servers=tuple(servers))


def _validate_mcp_http_url(server_name: str, url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"mcp server {server_name!r} has an invalid http url")
    if parsed.username or parsed.password:
        raise ValueError(f"mcp server {server_name!r} url must not contain credentials")
    if parsed.scheme == "https" or parsed.hostname == "localhost":
        return
    try:
        is_loopback = ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise ValueError(
            f"mcp server {server_name!r} requires https outside localhost"
        )


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
