from __future__ import annotations

from .models import Message, RuntimeResult
from .prompt_builder import PromptBuilder
from .session import InMemorySessionStore
from .store import SessionStore
from .tools import ToolRegistry
from .transports import ModelRequest, ModelTransport
from navi_agent.telemetry import TraceStore, RuntimeTrace


class AgentRuntime:
    def __init__(
        self,
        transport: ModelTransport,
        tool_registry: ToolRegistry | None = None,
        session_store: SessionStore | None = None,
        prompt_builder: PromptBuilder | None = None,
        trace_store: TraceStore | None = None,
        max_iterations: int = 8,
    ) -> None:
        self._transport = transport
        self._tool_registry = tool_registry or ToolRegistry()
        self._session_store = session_store or InMemorySessionStore()
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._trace_store = trace_store
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
            response = self._transport.generate(
                ModelRequest(
                    messages=self._session_store.snapshot(session),
                    tools=self._tool_registry.schemas(),
                )
            )

            assistant_message = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            self._session_store.append(session, assistant_message)

            if not response.tool_calls:
                result = RuntimeResult(
                    session_id=session.session_id,
                    status="success",
                    final_response=response.content,
                    messages=self._session_store.snapshot(session),
                    tool_results=tool_results,
                )
                self._record_trace(
                    session_id=session.session_id,
                    user_id=user_id,
                    user_message=user_message,
                    result=result,
                )
                return result

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

    def _record_trace(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        result: RuntimeResult,
    ) -> None:
        if self._trace_store is None:
            return
        self._trace_store.record(
            RuntimeTrace(
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                final_response=result.final_response,
                status=result.status,
                tool_names=[item.name for item in result.tool_results],
            )
        )
