from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from datetime import datetime, timezone
import logging
from time import perf_counter

from navi_agent.tooling import ToolContext, ToolPolicy, ToolResult
from navi_agent.tools.base import BaseTool

from .approval import ApprovalProvider, ApprovalRequest, DenyAllApprovalProvider
from .models import ToolCall

logger = logging.getLogger("navi_agent.runtime.tool_executor")

_MAX_TOOL_WORKERS = 8


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _stamp_result(result: ToolResult, *, started_at: str, started_perf: float) -> ToolResult:
    result.metadata.update(
        {
            "_trace_started_at": started_at,
            "_trace_completed_at": _utc_now_iso(),
            "_trace_duration_ms": int((perf_counter() - started_perf) * 1000),
        }
    )
    return result


def _tool_failure_result(*, name: str, tool_call_id: str, message: str, exception: Exception | None = None) -> ToolResult:
    structured_content: dict[str, object] = {"error": message}
    metadata: dict[str, object] = {}
    if exception is not None:
        structured_content["error_type"] = exception.__class__.__name__
        metadata["error_type"] = exception.__class__.__name__
    return ToolResult.error(
        name=name,
        content=message,
        structured_content=structured_content,
        metadata=metadata,
    ).bind(tool_call_id)


class ToolExecutor:
    def __init__(
        self,
        policy: ToolPolicy,
        approval_provider: ApprovalProvider | None = None,
    ) -> None:
        self._policy = policy
        self._approval_provider = approval_provider or DenyAllApprovalProvider()

    def can_execute_concurrently(
        self,
        tool_calls: list[ToolCall],
        context: ToolContext | None = None,
    ) -> bool:
        """Keep approval and denial flows on the sequential dispatch path."""
        return all(
            self._policy.decide(tool_call.name, tool_call.arguments, context).allows_execution
            for tool_call in tool_calls
        )

    def execute(
        self,
        tool_calls: list[ToolCall],
        tools_by_name: dict[str, BaseTool],
        context: ToolContext | None = None,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for tool_call in tool_calls:
            tool_context = _bind_tool_output(context, tool_call)
            started_at = _utc_now_iso()
            started_perf = perf_counter()
            tool = tools_by_name.get(tool_call.name)
            if tool is None:
                results.append(
                    _stamp_result(
                        _tool_failure_result(
                            name=tool_call.name,
                            tool_call_id=tool_call.id,
                            message=f"Unknown tool: {tool_call.name}",
                        ),
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                )
                continue

            decision = self._policy.decide(tool_call.name, tool_call.arguments, tool_context)
            if not decision.allows_execution:
                if decision.requires_approval:
                    approval_decision = self._approval_provider.request_approval(
                        ApprovalRequest(
                            tool_name=tool_call.name,
                            arguments=tool_call.arguments,
                            reason=decision.reason or f"Tool requires approval: {tool_call.name}",
                            context=tool_context,
                            metadata=decision.metadata,
                        )
                    )
                    if approval_decision.approved:
                        try:
                            output = tool.invoke(context=tool_context, **tool_call.arguments)
                            results.append(
                                _stamp_result(
                                    output.bind(tool_call.id, tool_call.name),
                                    started_at=started_at,
                                    started_perf=started_perf,
                                )
                            )
                        except Exception as exc:
                            logger.exception("Tool execution failed: %s", tool_call.name)
                            results.append(
                                _stamp_result(
                                    _tool_failure_result(
                                        name=tool_call.name,
                                        tool_call_id=tool_call.id,
                                        message=f"Tool execution failed: {exc}",
                                        exception=exc,
                                    ),
                                    started_at=started_at,
                                    started_perf=started_perf,
                                )
                            )
                        continue
                    results.append(
                        _stamp_result(
                            ToolResult.error(
                                name=tool_call.name,
                                content=approval_decision.reason or decision.reason or f"Tool blocked: {tool_call.name}",
                                structured_content={
                                    "approval_required": True,
                                    "interaction_pending": approval_decision.metadata.get(
                                        "interaction_pending"
                                    )
                                    is True,
                                    "interaction_kind": approval_decision.metadata.get(
                                        "interaction_kind"
                                    ),
                                    "interaction_id": approval_decision.metadata.get(
                                        "interaction_id"
                                    ),
                                    "prompt": approval_decision.metadata.get("prompt"),
                                    "tool_name": tool_call.name,
                                    "arguments": tool_call.arguments,
                                },
                                metadata=approval_decision.metadata or decision.metadata,
                            ).bind(tool_call.id),
                            started_at=started_at,
                            started_perf=started_perf,
                        )
                    )
                    continue
                results.append(
                    _stamp_result(
                        _tool_failure_result(
                            name=tool_call.name,
                            tool_call_id=tool_call.id,
                            message=decision.reason or f"Tool blocked: {tool_call.name}",
                        ),
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                )
                continue

            try:
                output = tool.invoke(context=tool_context, **tool_call.arguments)
                results.append(
                    _stamp_result(
                        output.bind(tool_call.id, tool_call.name),
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                )
            except Exception as exc:
                logger.exception("Tool execution failed: %s", tool_call.name)
                results.append(
                    _stamp_result(
                        _tool_failure_result(
                            name=tool_call.name,
                            tool_call_id=tool_call.id,
                            message=f"Tool execution failed: {exc}",
                            exception=exc,
                        ),
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                )
        return results

    def execute_concurrently(
        self,
        tool_calls: list[ToolCall],
        tools_by_name: dict[str, BaseTool],
        context: ToolContext | None = None,
    ) -> list[ToolResult]:
        """Execute independent tool calls concurrently and preserve call order."""
        if len(tool_calls) <= 1:
            return self.execute(tool_calls, tools_by_name, context)

        max_workers = min(len(tool_calls), _MAX_TOOL_WORKERS)
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="navi-tool",
        ) as executor:
            futures = [
                executor.submit(
                    copy_context().run,
                    self.execute,
                    [tool_call],
                    tools_by_name,
                    context,
                )
                for tool_call in tool_calls
            ]
            return [future.result()[0] for future in futures]


def _bind_tool_output(context: ToolContext | None, tool_call: ToolCall) -> ToolContext | None:
    if context is None or context.emit_output is None:
        return context

    def emit_output(payload: dict[str, object]) -> None:
        context.emit_output(
            {
                **payload,
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
            }
        )

    return replace(context, emit_output=emit_output)
