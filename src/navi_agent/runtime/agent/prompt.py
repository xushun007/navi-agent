from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from navi_agent.memory import MemoryStore

from ..models import Message
from .prompt_contributors import (
    BASE_SYSTEM_PROMPT,
    MEMORY_GUIDANCE,
    SKILL_GUIDANCE,
    BaseGuidanceContributor,
    MemoryPromptContributor,
    ProjectContextContributor,
    RequestedSystemPromptContributor,
    SkillIndexPromptContributor,
    SkillIndexStore,
    WorkspacePromptContributor,
)
from .prompt_pipeline import PromptParts, PromptPipeline, PromptRequest


class PromptBuilder:
    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        profile_memory_limit: int = 3,
        relevant_memory_limit: int = 5,
        skill_store: SkillIndexStore | None = None,
        project_context_root: Path | None = None,
        additional_workspace_roots: Iterable[Path] | None = None,
    ) -> None:
        self._memory_store = memory_store
        self._profile_memory_limit = profile_memory_limit
        self._relevant_memory_limit = relevant_memory_limit
        self._skill_store = skill_store
        self._project_context_root = project_context_root
        self._additional_workspace_roots = tuple(
            Path(root).resolve() for root in additional_workspace_roots or ()
        )
        self._pipeline = PromptPipeline(
            [
                BaseGuidanceContributor(),
                RequestedSystemPromptContributor(),
                WorkspacePromptContributor(
                    project_root=self._project_context_root,
                    additional_roots=self._additional_workspace_roots,
                ),
                ProjectContextContributor(self._project_context_root),
                MemoryPromptContributor(
                    self._memory_store,
                    profile_limit=self._profile_memory_limit,
                    relevant_limit=self._relevant_memory_limit,
                ),
                SkillIndexPromptContributor(self._skill_store),
            ]
        )
        self._last_injected_skill_names: list[str] = []
        self._last_injected_context_files: list[str] = []

    @property
    def last_injected_skill_names(self) -> list[str]:
        return list(self._last_injected_skill_names)

    @property
    def last_injected_context_files(self) -> list[str]:
        return list(self._last_injected_context_files)

    def build_run_system_message(
        self,
        *,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
    ) -> Message:
        prompt = self.build_system_prompt(
            user_id=user_id,
            user_message=user_message,
            system_prompt=system_prompt,
        )
        return Message(role="system", content=prompt.render())

    def build_system_prompt(
        self,
        *,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
    ) -> PromptParts:
        self._last_injected_skill_names = []
        self._last_injected_context_files = []
        result = self._pipeline.build(
            PromptRequest(
                user_id=user_id,
                user_message=user_message,
                system_prompt=system_prompt,
            )
        )
        self._last_injected_context_files = list(
            result.references_from(ProjectContextContributor.name)
        )
        return PromptParts(
            stable=result.parts.stable,
            context=result.parts.context,
            volatile=result.parts.volatile,
        )
