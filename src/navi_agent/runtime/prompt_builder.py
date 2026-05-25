from __future__ import annotations

from .models import ConversationState, Message


class PromptBuilder:
    def build_initial_messages(
        self,
        session: ConversationState,
        user_message: str,
        system_prompt: str | None = None,
    ) -> list[Message]:
        messages: list[Message] = []
        if system_prompt and not session.messages:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=user_message))
        return messages
