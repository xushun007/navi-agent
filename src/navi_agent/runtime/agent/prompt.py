from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from navi_agent.memory import MemoryStore
from navi_agent.memory.validation import sanitize_memory_for_prompt

from ..models import Message
from .prompt_contributors import (
    BASE_SYSTEM_PROMPT,
    MEMORY_GUIDANCE,
    SKILL_GUIDANCE,
    BaseGuidanceContributor,
    ProjectContextContributor,
    RequestedSystemPromptContributor,
    WorkspacePromptContributor,
)
from .prompt_pipeline import PromptParts, PromptPipeline, PromptRequest


class SkillIndexStore(Protocol):
    def list(self): ...


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
        if profile_memory_limit <= 0:
            raise ValueError("profile_memory_limit must be positive")
        if relevant_memory_limit <= 0:
            raise ValueError("relevant_memory_limit must be positive")
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
        volatile_parts = []
        memory_block = self._build_memory_block(user_id, user_message)
        if memory_block:
            volatile_parts.append(memory_block)
        skill_block = self._build_skill_block()
        if skill_block:
            volatile_parts.append(skill_block)
        return PromptParts(
            stable=result.parts.stable,
            context=result.parts.context,
            volatile="\n\n".join(volatile_parts),
        )

    def _build_memory_block(self, user_id: str, user_message: str) -> str | None:
        if self._memory_store is None:
            return None
        recall = self._memory_store.recall_for_user(
            user_id,
            user_message,
            profile_limit=self._profile_memory_limit,
            relevant_limit=self._relevant_memory_limit,
        )
        if not recall.profile and not recall.relevant:
            return None
        lines = ["[Memory]"]
        if recall.profile:
            lines.append("User Profile:")
            lines.extend(
                f"- [{record.kind}] {sanitize_memory_for_prompt(record.content)}"
                for record in recall.profile
            )
        if recall.relevant:
            lines.append("Relevant Facts:")
            lines.extend(
                f"- [{record.kind}] {sanitize_memory_for_prompt(record.content)}"
                for record in recall.relevant
            )
        return "\n".join(lines)

    def _build_skill_block(self) -> str | None:
        if self._skill_store is None:
            return None
        records = self._skill_store.list()
        if not records:
            return None
        lines = [
            "[Skills]",
            "Available reusable procedures. Scan this index before execution. "
            "If one matches or is partially relevant, call skill_view(skill_name='<name>') "
            "to load the full SKILL.md before using it.",
        ]
        categories: dict[str, list] = {}
        for record in records:
            category = str(getattr(record, "category", "general") or "general")
            categories.setdefault(category, []).append(record)
        for category in sorted(categories):
            lines.append(f"  {category}:")
            for record in sorted(categories[category], key=lambda item: item.name):
                if record.description:
                    lines.append(f"    - {record.name}: {record.description}")
                else:
                    lines.append(f"    - {record.name}")
        return "\n".join(lines)
