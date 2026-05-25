from __future__ import annotations

from typing import Protocol

from .models import Message, ModelResponse, RuntimeResult
from .prompt_builder import PromptBuilder
from .session import InMemorySessionStore
from .store import SessionStore
from .tools import ToolRegistry


class ModelClient(Protocol):
    def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, str]],
    ) -> ModelResponse: ...


class AgentRuntime:
    def __init__(
        self,
        model_client: ModelClient,
        tool_registry: ToolRegistry | None = None,
        session_store: SessionStore | None = None,
        prompt_builder: PromptBuilder | None = None,
        max_iterations: int = 8,
    ) -> None:
        self._model_client = model_client
        self._tool_registry = tool_registry or ToolRegistry()
        self._session_store = session_store or InMemorySessionStore()
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._max_iterations = max_iterations

    def run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
    ) -> RuntimeResult:
        session = self._session_store.load(session_id=session_id, user_id=user_id)
        for message in self._prompt_builder.build_initial_messages(
            session=session,
            user_message=user_message,
            system_prompt=system_prompt,
        ):
            self._session_store.append(session, message)
        tool_results = []

        for _ in range(self._max_iterations):
            response = self._model_client.generate(
                messages=self._session_store.snapshot(session),
                tools=self._tool_registry.schemas(),
            )

            assistant_message = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            self._session_store.append(session, assistant_message)

            if not response.tool_calls:
                return RuntimeResult(
                    session_id=session.session_id,
                    status="success",
                    final_response=response.content,
                    messages=self._session_store.snapshot(session),
                    tool_results=tool_results,
                )

            for tool_result in self._tool_registry.dispatch(response.tool_calls):
                tool_results.append(tool_result)
                self._session_store.append(
                    session,
                    Message(
                        role="tool",
                        content=tool_result.content,
                        tool_call_id=tool_result.tool_call_id,
                    ),
                )

        raise RuntimeError("Runtime iteration limit exceeded")
