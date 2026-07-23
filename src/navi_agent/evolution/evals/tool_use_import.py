from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from navi_agent.telemetry import RuntimeTrajectory

from .tool_use import ToolUseEvalCase


def build_tool_use_case_from_trajectory(
    trajectory: RuntimeTrajectory,
    *,
    level: str = "L1",
) -> ToolUseEvalCase | None:
    if trajectory.empty:
        return None
    prompt = _first_user_message(trajectory)
    if not prompt:
        return None
    tool_calls = _tool_calls(trajectory)
    run_id = trajectory.run_id or trajectory.events[0].run_id
    return ToolUseEvalCase(
        id=f"tooluse_replay_{_safe_id(trajectory.session_id)}_{run_id[:8]}",
        level=level.upper(),
        category="tool_use.replay",
        prompt=prompt,
        source_inspiration="runtime-events",
        required_tools=_unique([str(item["name"]) for item in tool_calls]),
        forbidden_tools=[],
        expected_args={
            str(item["name"]): dict(item["arguments"])
            for item in tool_calls
            if isinstance(item.get("arguments"), dict)
        },
        approval_required_tools=[],
        max_iterations=max(6, _max_iteration(trajectory)),
        grader="trace_and_answer",
        expected_outcome="Replay-derived case should preserve the observed tool-use path.",
        notes=f"Generated from runtime event trajectory: session_id={trajectory.session_id} run_id={run_id}",
    )


def render_tool_use_case_jsonl(case: ToolUseEvalCase) -> str:
    return json.dumps(asdict(case), ensure_ascii=False, sort_keys=True)


def _first_user_message(trajectory: RuntimeTrajectory) -> str:
    for event in trajectory.events:
        if event.name == "user.message":
            return str(event.payload.get("content") or "").strip()
    return ""


def _tool_calls(trajectory: RuntimeTrajectory) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in trajectory.events:
        if event.name != "tool.call":
            continue
        tool_name = str(event.payload.get("tool_name") or "").strip()
        if not tool_name:
            continue
        arguments = event.payload.get("arguments")
        calls.append(
            {
                "name": tool_name,
                "arguments": dict(arguments) if isinstance(arguments, dict) else {},
            }
        )
    return calls


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _max_iteration(trajectory: RuntimeTrajectory) -> int:
    iterations = [event.iteration for event in trajectory.events if event.iteration is not None]
    if not iterations:
        return 3
    return max(iterations) + 2


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_") or "session"
