from __future__ import annotations

from navi_agent.app import ApplicationService
from navi_agent.config import ModelSettings, RuntimeSettings, load_config
from navi_agent.logging import setup_logging
from navi_agent.memory import InMemoryMemoryStore
from navi_agent.paths import get_app_log_path, get_state_db_path
from navi_agent.runtime import AgentRuntime, PromptBuilder, SQLiteSessionStore, build_transport
from navi_agent.tools.defaults import build_default_tool_registry


def build_runtime(
    model_settings: ModelSettings | None = None,
    runtime_settings: RuntimeSettings | None = None,
) -> AgentRuntime:
    config = load_config()
    model_settings = model_settings or ModelSettings.from_sources(config)
    runtime_settings = runtime_settings or RuntimeSettings.from_sources(config)

    setup_logging(
        level="INFO",
        log_path=get_app_log_path(),
    )

    transport = build_transport(model_settings)
    session_store = SQLiteSessionStore(get_state_db_path())
    memory_store = InMemoryMemoryStore()

    return AgentRuntime(
        transport=transport,
        session_store=session_store,
        prompt_builder=PromptBuilder(memory_store=memory_store),
        tool_registry=build_default_tool_registry(memory_store=memory_store),
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
