from __future__ import annotations

from navi_agent.app import ApplicationService
from navi_agent.config import ModelSettings, RuntimeSettings
from navi_agent.logging import setup_logging
from navi_agent.paths import get_app_log_path, get_state_db_path
from navi_agent.runtime import AgentRuntime, SQLiteSessionStore, build_transport


def build_runtime(
    model_settings: ModelSettings | None = None,
    runtime_settings: RuntimeSettings | None = None,
) -> AgentRuntime:
    model_settings = model_settings or ModelSettings.from_env()
    runtime_settings = runtime_settings or RuntimeSettings.from_env()

    setup_logging(
        level=runtime_settings.log_level,
        log_path=get_app_log_path(),
    )

    transport = build_transport(model_settings)
    session_store = SQLiteSessionStore(get_state_db_path())

    return AgentRuntime(
        transport=transport,
        session_store=session_store,
        max_iterations=runtime_settings.max_iterations,
    )


def build_application(
    model_settings: ModelSettings | None = None,
    runtime_settings: RuntimeSettings | None = None,
    default_system_prompt: str | None = None,
) -> ApplicationService:
    runtime = build_runtime(
        model_settings=model_settings,
        runtime_settings=runtime_settings,
    )
    return ApplicationService(
        runtime=runtime,
        default_system_prompt=default_system_prompt,
    )
