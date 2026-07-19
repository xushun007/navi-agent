from __future__ import annotations

from dataclasses import dataclass

from navi_agent.config import (
    LangfuseSettings,
    ModelSettings,
    RuntimeSettings,
    WeixinGatewaySettings,
    load_config,
)
from navi_agent.paths import get_app_log_path, get_config_path, get_navi_home, get_state_db_path
from navi_agent.runtime import build_transport
from navi_agent.telemetry import LangfuseTraceExporter, is_langfuse_sdk_available


@dataclass(slots=True)
class DoctorReport:
    ok: bool
    lines: list[str]


def collect_report(*, gateway: str | None = None) -> DoctorReport:
    config_path = get_config_path()
    config = load_config(config_path)
    model_settings = ModelSettings.from_sources(config)
    runtime_settings = RuntimeSettings.from_sources(config)
    langfuse_settings = LangfuseSettings.from_sources(config)

    lines = [
        f"navi_home: {get_navi_home()}",
        f"config_path: {config_path}",
        f"config_exists: {_format_bool(config_path.exists())}",
        f"state_db_path: {get_state_db_path()}",
        f"log_path: {get_app_log_path()}",
        f"model: {model_settings.model}",
        f"base_url: {model_settings.base_url or '(default)'}",
        f"api_key_configured: {_format_bool(bool(model_settings.api_key))}",
        f"max_iterations: {runtime_settings.max_iterations}",
        f"langfuse_enabled: {_format_bool(langfuse_settings.enabled)}",
        f"langfuse_sdk_installed: {_format_bool(is_langfuse_sdk_available())}",
    ]

    ok = True
    try:
        build_transport(model_settings)
        lines.append("transport: ok")
    except Exception as exc:
        ok = False
        lines.append(f"transport: error: {exc}")

    if langfuse_settings.enabled:
        langfuse_ready = bool(langfuse_settings.public_key and langfuse_settings.secret_key)
        lines.append(f"langfuse_keys_configured: {_format_bool(langfuse_ready)}")
        if not langfuse_ready:
            ok = False
            lines.append("langfuse_exporter: error: missing public_key or secret_key")
        else:
            try:
                LangfuseTraceExporter.from_settings(langfuse_settings)
            except Exception as exc:
                ok = False
                lines.append(f"langfuse_exporter: error: {exc}")
            else:
                lines.append("langfuse_exporter: ok")
    if gateway == "weixin":
        gateway_report = _collect_weixin_gateway_report(config)
        ok = ok and gateway_report.ok
        lines.extend(gateway_report.lines)
    return DoctorReport(ok=ok, lines=lines)


def run_doctor(output_fn=print, *, gateway: str | None = None) -> int:
    report = collect_report(gateway=gateway)
    for line in report.lines:
        output_fn(line)
    return 0 if report.ok else 1


def _collect_weixin_gateway_report(config: dict) -> DoctorReport:
    settings = WeixinGatewaySettings.from_sources(config)
    lines = [
        "gateway: weixin",
        f"weixin_base_url: {settings.base_url}",
        f"weixin_token_configured: {_format_bool(bool(settings.token))}",
        f"weixin_account_id_configured: {_format_bool(bool(settings.account_id))}",
        f"weixin_dm_policy: {settings.dm_policy}",
    ]
    ok = bool(settings.token and settings.account_id)
    if not settings.token:
        lines.append("weixin_gateway: error: missing gateway.weixin.token")
    if not settings.account_id:
        lines.append("weixin_gateway: error: missing gateway.weixin.account_id")
    if ok:
        lines.append("weixin_gateway: ok")
    return DoctorReport(ok=ok, lines=lines)


def _format_bool(value: bool) -> str:
    return "yes" if value else "no"
