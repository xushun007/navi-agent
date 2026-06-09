from __future__ import annotations

from datetime import datetime, timezone
import logging
from time import perf_counter

from navi_agent.tooling import ToolContext, ToolPolicy, ToolResult
from navi_agent.tools.base import BaseTool

from .approval import ApprovalProvider, ApprovalRequest, DenyAllApprovalProvider
from .models import ToolCall

logger = logging.getLogger("navi_agent.runtime.tool_executor")


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


class ToolExecutor:
    def __init__(
        self,
        policy: ToolPolicy,
        approval_provider: ApprovalProvider | None = None,
    ) -> None:
        self._policy = policy
        self._approval_provider = approval_provider or DenyAllApprovalProvider()

    def execute(
        self,
        tool_calls: list[ToolCall],
        tools_by_name: dict[str, BaseTool],
        context: ToolContext | None = None,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for tool_call in tool_calls:
            started_at = _utc_now_iso()
            started_perf = perf_counter()
            tool = tools_by_name.get(tool_call.name)
            if tool is None:
                results.append(
                    _stamp_result(
                        ToolResult.error(
                            name=tool_call.name,
                            content=f"Unknown tool: {tool_call.name}",
                        ).bind(tool_call.id),
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                )
                continue

            decision = self._policy.decide(tool_call.name, tool_call.arguments, context)
            if not decision.allows_execution:
                if decision.requires_approval:
                    approval_decision = self._approval_provider.request_approval(
                        ApprovalRequest(
                            tool_name=tool_call.name,
                            arguments=tool_call.arguments,
                            reason=decision.reason or f"Tool requires approval: {tool_call.name}",
                            context=context,
                            metadata=decision.metadata,
                        )
                    )
                    if approval_decision.approved:
                        try:
                            output = tool.invoke(context=context, **tool_call.arguments)
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
                                    ToolResult.error(
                                        name=tool_call.name,
                                        content=f"Tool execution failed: {exc}",
                                    ).bind(tool_call.id),
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
                        ToolResult.error(
                            name=tool_call.name,
                            content=decision.reason or f"Tool blocked: {tool_call.name}",
                            metadata=decision.metadata,
                        ).bind(tool_call.id),
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                )
                continue

            try:
                output = tool.invoke(context=context, **tool_call.arguments)
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
                        ToolResult.error(
                            name=tool_call.name,
                            content=f"Tool execution failed: {exc}",
                        ).bind(tool_call.id),
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                )
        return results
