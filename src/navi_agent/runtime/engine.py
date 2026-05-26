from __future__ import annotations

import logging
from collections.abc import Sequence

from .models import Message, RuntimeEvent, RuntimeResult, ToolContext
from .observers import RuntimeObserver
from .prompt_builder import PromptBuilder
from .session import InMemorySessionStore
from .store import SessionStore
from .tool_result_renderer import DefaultToolResultRenderer, ToolResultRenderer
from .tools import ToolRegistry
from .transports import ModelRequest, ModelTransport
from navi_agent.telemetry import TraceStore, RuntimeTrace

logger = logging.getLogger("navi_agent.runtime")


class AgentRuntime:
    def __init__(
        self,
        transport: ModelTransport,
        tool_registry: ToolRegistry | None = None,
        session_store: SessionStore | None = None,
        prompt_builder: PromptBuilder | None = None,
        trace_store: TraceStore | None = None,
        observers: Sequence[RuntimeObserver] | None = None,
        tool_result_renderer: ToolResultRenderer | None = None,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
        max_iterations: int = 8,
    ) -> None:
        self._transport = transport
        self._tool_registry = tool_registry or ToolRegistry()
        self._session_store = session_store or InMemorySessionStore()
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._trace_store = trace_store
        self._observers = list(observers or [])
        self._tool_result_renderer = tool_result_renderer or DefaultToolResultRenderer()
        self._enabled_toolsets = enabled_toolsets
        self._disabled_toolsets = disabled_toolsets
        self._max_iterations = max_iterations

    def run_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        system_prompt: str | None = None,
    ) -> RuntimeResult:
        logger.info("Starting runtime conversation: session_id=%s user_id=%s", session_id, user_id)
        self._emit_event(
            RuntimeEvent(
                name="runtime.started",
                session_id=session_id,
                user_id=user_id,
            )
        )
        session = self._session_store.load(session_id=session_id, user_id=user_id)
        for message in self._prompt_builder.build_initial_messages(
            session=session,
            user_message=user_message,
            system_prompt=system_prompt,
        ):
            self._session_store.append(session, message)
        tool_results = []

        for iteration in range(self._max_iterations):
            iteration_number = iteration + 1
            logger.debug(
                "Running iteration: session_id=%s iteration=%s",
                session_id,
                iteration_number,
            )
            self._emit_event(
                RuntimeEvent(
                    name="iteration.started",
                    session_id=session_id,
                    user_id=user_id,
                    iteration=iteration_number,
                )
            )
            response = self._transport.generate(
                ModelRequest(
                    messages=self._session_store.snapshot(session),
                    tools=self._tool_registry.schemas(
                        enabled_toolsets=self._enabled_toolsets,
                        disabled_toolsets=self._disabled_toolsets,
                    ),
                )
            )
            self._emit_event(
                RuntimeEvent(
                    name="model.responded",
                    session_id=session_id,
                    user_id=user_id,
                    iteration=iteration_number,
                    metadata={"tool_call_count": len(response.tool_calls)},
                )
            )

            assistant_message = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            self._session_store.append(session, assistant_message)

            if not response.tool_calls:
                logger.info(
                    "Runtime conversation completed: session_id=%s status=success",
                    session_id,
                )
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
                self._emit_event(
                    RuntimeEvent(
                        name="runtime.completed",
                        session_id=session.session_id,
                        user_id=user_id,
                        iteration=iteration_number,
                        metadata={"status": result.status},
                    )
                )
                return result

            tool_context = ToolContext(
                session_id=session.session_id,
                user_id=user_id,
                iteration=iteration_number,
            )
            for tool_result in self._tool_registry.dispatch(
                response.tool_calls,
                context=tool_context,
                enabled_toolsets=self._enabled_toolsets,
                disabled_toolsets=self._disabled_toolsets,
            ):
                logger.debug(
                    "Tool executed: session_id=%s tool=%s",
                    session_id,
                    tool_result.name,
                )
                tool_results.append(tool_result)
                self._emit_event(
                    RuntimeEvent(
                        name="tool.executed",
                        session_id=session_id,
                        user_id=user_id,
                        iteration=iteration_number,
                        metadata={
                            "tool_name": tool_result.name,
                            "status": tool_result.status,
                        },
                    )
                )
                self._session_store.append(
                    session,
                    Message(
                        role="tool",
                        content=self._tool_result_renderer.render(tool_result),
                        tool_call_id=tool_result.tool_call_id,
                    ),
                )

        logger.error("Runtime iteration limit exceeded: session_id=%s", session_id)
        result = RuntimeResult(
            session_id=session.session_id,
            status="iteration_limit_exceeded",
            final_response="",
            messages=self._session_store.snapshot(session),
            tool_results=tool_results,
        )
        self._record_trace(
            session_id=session.session_id,
            user_id=user_id,
            user_message=user_message,
            result=result,
        )
        self._emit_event(
            RuntimeEvent(
                name="runtime.completed",
                session_id=session.session_id,
                user_id=user_id,
                iteration=self._max_iterations,
                metadata={"status": result.status},
            )
        )
        return result

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

    def _emit_event(self, event: RuntimeEvent) -> None:
        for observer in self._observers:
            observer.on_event(event)
