from __future__ import annotations

from navi_agent.memory import MemoryStore

from .models import ConversationState, Message


class PromptBuilder:
    def __init__(self, memory_store: MemoryStore | None = None, memory_limit: int = 5) -> None:
        if memory_limit <= 0:
            raise ValueError("memory_limit must be positive")
        self._memory_store = memory_store
        self._memory_limit = memory_limit

    def build_initial_messages(
        self,
        session: ConversationState,
        user_message: str,
        system_prompt: str | None = None,
    ) -> list[Message]:
        messages: list[Message] = []
        if not session.messages:
            system_parts = []
            if system_prompt:
                system_parts.append(system_prompt)
            memory_block = self._build_memory_block(session.user_id)
            if memory_block:
                system_parts.append(memory_block)
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
        lines.extend(f"- {record.content}" for record in records)
        return "\n".join(lines)
