from __future__ import annotations

from navi_agent.evolution import FileSkillStore
from navi_agent.memory import MemoryStore

from .models import ConversationState, Message


class PromptBuilder:
    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        memory_limit: int = 5,
        skill_store: FileSkillStore | None = None,
        skill_limit: int = 3,
    ) -> None:
        if memory_limit <= 0:
            raise ValueError("memory_limit must be positive")
        if skill_limit <= 0:
            raise ValueError("skill_limit must be positive")
        self._memory_store = memory_store
        self._memory_limit = memory_limit
        self._skill_store = skill_store
        self._skill_limit = skill_limit
        self._last_injected_skill_names: list[str] = []

    @property
    def last_injected_skill_names(self) -> list[str]:
        return list(self._last_injected_skill_names)

    def build_initial_messages(
        self,
        session: ConversationState,
        user_message: str,
        system_prompt: str | None = None,
    ) -> list[Message]:
        self._last_injected_skill_names = []
        messages: list[Message] = []
        if not session.messages:
            system_parts = []
            if system_prompt:
                system_parts.append(system_prompt)
            memory_block = self._build_memory_block(session.user_id)
            if memory_block:
                system_parts.append(memory_block)
            skill_block = self._build_skill_block(user_message)
            if skill_block:
                system_parts.append(skill_block)
            if system_parts:
                messages.append(Message(role="system", content="\n\n".join(system_parts)))
        messages.append(Message(role="user", content=user_message))
        return messages

    def _build_memory_block(self, user_id: str) -> str | None:
        if self._memory_store is None:
            return None
        records = self._memory_store.list_for_user(user_id)[-self._memory_limit :]
        if not records:
            return None
        lines = ["[Memory]"]
        lines.extend(f"- [{record.kind}] {record.content}" for record in records)
        return "\n".join(lines)

    def _build_skill_block(self, user_message: str) -> str | None:
        if self._skill_store is None:
            return None
        records = self._skill_store.search(user_message, limit=self._skill_limit)
        if not records:
            return None
        self._last_injected_skill_names = [record.name for record in records]
        lines = ["[Skills]", "Relevant reusable procedures:"]
        for record in records:
            lines.append(f"- {record.name}: {record.description}")
        return "\n".join(lines)
