from __future__ import annotations

import logging
from pathlib import Path

from navi_agent.app import ApplicationService
from navi_agent.config import LangfuseSettings, ModelSettings, RuntimeSettings, load_config
from navi_agent.evolution import (
    FileSkillStore,
    JsonlCandidateStore,
    JsonlEvalCaseStore,
    JsonlReviewRunStore,
    PromptOverlayStore,
    ReviewAgentService,
    SkillProvenanceStore,
    SkillUsageStore,
)
from navi_agent.logging import setup_logging
from navi_agent.memory import FileMemoryStore
from navi_agent.paths import (
    get_app_log_path,
    get_candidate_store_path,
    get_memories_dir,
    get_prompt_overlay_path,
    get_prompt_overlay_snapshots_dir,
    get_runtime_event_store_path,
    get_review_run_store_path,
    get_skills_dir,
    get_state_db_path,
    get_trace_store_path,
    get_eval_case_store_path,
)
from navi_agent.runtime import AgentRuntime, PromptBuilder, SQLiteSessionStore, build_transport
from navi_agent.runtime.approval import ApprovalProvider
from navi_agent.telemetry import (
    CompositeTraceStore,
    JsonlRuntimeEventStore,
    JsonlTraceStore,
    LangfuseTraceExporter,
)
from navi_agent.tools.defaults import build_default_tool_registry

logger = logging.getLogger("navi_agent.bootstrap")


def build_runtime(
    model_settings: ModelSettings | None = None,
    runtime_settings: RuntimeSettings | None = None,
    approval_provider: ApprovalProvider | None = None,
    skill_store: FileSkillStore | None = None,
    memory_store: FileMemoryStore | None = None,
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
    memory_store = memory_store or FileMemoryStore(get_memories_dir())
    skill_store = skill_store or FileSkillStore(get_skills_dir())
    trace_store = _build_trace_store(config)

    return AgentRuntime(
        transport=transport,
        session_store=session_store,
        prompt_builder=PromptBuilder(
            memory_store=memory_store,
            skill_store=skill_store,
            project_context_root=Path.cwd(),
        ),
        trace_store=trace_store,
        event_store=JsonlRuntimeEventStore(get_runtime_event_store_path()),
        tool_registry=build_default_tool_registry(
            memory_store=memory_store,
            approval_provider=approval_provider,
            skill_store=skill_store,
        ),
        max_iterations=runtime_settings.max_iterations,
    )


def build_application(
    model_settings: ModelSettings | None = None,
    runtime_settings: RuntimeSettings | None = None,
    default_system_prompt: str | None = None,
    approval_provider: ApprovalProvider | None = None,
) -> ApplicationService:
    config = load_config()
    review_model_settings = model_settings or ModelSettings.from_sources(config)
    skill_store = FileSkillStore(get_skills_dir())
    memory_store = FileMemoryStore(get_memories_dir())
    runtime = build_runtime(
        model_settings=model_settings,
        runtime_settings=runtime_settings,
        approval_provider=approval_provider,
        skill_store=skill_store,
        memory_store=memory_store,
    )
    prompt_overlay_store = PromptOverlayStore(
        get_prompt_overlay_path(),
        get_prompt_overlay_snapshots_dir(),
    )
    prompt_overlay = prompt_overlay_store.get()
    default_prompt = default_system_prompt
    if prompt_overlay:
        default_prompt = "\n\n".join(
            part for part in [default_system_prompt, prompt_overlay] if part
        ) or None
    return ApplicationService(
        runtime=runtime,
        default_system_prompt=default_prompt,
        candidate_store=JsonlCandidateStore(get_candidate_store_path()),
        eval_case_store=JsonlEvalCaseStore(get_eval_case_store_path()),
        prompt_overlay_store=prompt_overlay_store,
        skill_store=skill_store,
        skill_provenance_store=SkillProvenanceStore(get_skills_dir()),
        skill_usage_store=SkillUsageStore(get_skills_dir()),
        memory_store=memory_store,
        review_run_store=JsonlReviewRunStore(get_review_run_store_path()),
        review_agent_service=ReviewAgentService(
            transport=build_transport(review_model_settings),
            memory_store=memory_store,
            skill_store=skill_store,
        ),
    )


def _build_trace_store(config: dict) -> JsonlTraceStore | CompositeTraceStore:
    primary = JsonlTraceStore(get_trace_store_path())
    settings = LangfuseSettings.from_sources(config)
    if not settings.enabled:
        return primary
    try:
        exporter = LangfuseTraceExporter.from_settings(settings)
    except Exception:
        logger.exception("Failed to initialize Langfuse exporter")
        return primary
    return CompositeTraceStore(primary=primary, exporters=[exporter])
