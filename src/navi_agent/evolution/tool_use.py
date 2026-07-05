from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from navi_agent.telemetry import RuntimeTrace


@dataclass(slots=True)
class ToolUseEvalCase:
    id: str
    level: str
    category: str
    prompt: str
    source_inspiration: str
    required_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    expected_args: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_iterations: int = 3
    grader: str = "trace"
    expected_outcome: str = ""
    notes: str = ""


@dataclass(slots=True)
class ToolUseEvalResult:
    case_id: str
    level: str
    passed: bool
    score: float
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolUseEvalCaseStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list_cases(self) -> list[ToolUseEvalCase]:
        if not self.path.exists():
            return []
        cases: list[ToolUseEvalCase] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            cases.append(
                ToolUseEvalCase(
                    id=str(payload["id"]),
                    level=str(payload["level"]),
                    category=str(payload["category"]),
                    prompt=str(payload["prompt"]),
                    source_inspiration=str(payload.get("source_inspiration", "")),
                    required_tools=list(payload.get("required_tools") or []),
                    forbidden_tools=list(payload.get("forbidden_tools") or []),
                    expected_args=dict(payload.get("expected_args") or {}),
                    max_iterations=int(payload.get("max_iterations", 3)),
                    grader=str(payload.get("grader", "trace")),
                    expected_outcome=str(payload.get("expected_outcome", "")),
                    notes=str(payload.get("notes", "")),
                )
            )
        return cases

    def write_cases(self, cases: list[ToolUseEvalCase]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for case in cases:
                handle.write(json.dumps(asdict(case), ensure_ascii=False, sort_keys=True))
                handle.write("\n")


class ToolUseEvaluator:
    def evaluate(self, case: ToolUseEvalCase, trace: RuntimeTrace) -> ToolUseEvalResult:
        tool_calls = list(trace.tool_executions)
        tool_names = [execution.tool_name for execution in tool_calls]
        missing_tools = [tool for tool in case.required_tools if tool not in tool_names]
        forbidden_tools = [tool for tool in case.forbidden_tools if tool in tool_names]
        arg_mismatches = self._arg_mismatches(case, trace)
        signals: list[str] = []

        if trace.status != "success":
            signals.append(f"status:{trace.status}")
        if missing_tools:
            signals.append(f"missing_tools:{','.join(missing_tools)}")
        if forbidden_tools:
            signals.append(f"forbidden_tools:{','.join(forbidden_tools)}")
        if arg_mismatches:
            signals.append(f"arg_mismatches:{','.join(arg_mismatches)}")
        if trace.total_iterations > case.max_iterations:
            signals.append(f"iterations:{trace.total_iterations}>{case.max_iterations}")
        if trace.error_count:
            signals.append(f"tool_errors:{trace.error_count}")
        if not trace.final_response.strip():
            signals.append("empty_response")

        score = self._score(signals)
        passed = score >= 1.0
        return ToolUseEvalResult(
            case_id=case.id,
            level=case.level,
            passed=passed,
            score=score,
            summary="pass" if passed else "; ".join(signals),
            metadata={
                "category": case.category,
                "source_inspiration": case.source_inspiration,
                "tool_names": tool_names,
                "required_tools": list(case.required_tools),
                "forbidden_tools": list(case.forbidden_tools),
                "missing_tools": missing_tools,
                "forbidden_tool_hits": forbidden_tools,
                "arg_mismatches": arg_mismatches,
                "total_iterations": trace.total_iterations,
                "error_count": trace.error_count,
                "status": trace.status,
                "grader": case.grader,
                "signals": signals,
            },
        )

    @staticmethod
    def _score(signals: list[str]) -> float:
        if not signals:
            return 1.0
        score = 1.0
        for signal in signals:
            if signal.startswith("status:"):
                score -= 0.4
            elif signal.startswith("missing_tools:"):
                score -= 0.35
            elif signal.startswith("forbidden_tools:"):
                score -= 0.5
            elif signal.startswith("arg_mismatches:"):
                score -= 0.25
            elif signal.startswith("tool_errors:"):
                score -= 0.25
            elif signal == "empty_response":
                score -= 0.2
            else:
                score -= 0.1
        return max(0.0, round(score, 3))

    @staticmethod
    def _arg_mismatches(case: ToolUseEvalCase, trace: RuntimeTrace) -> list[str]:
        mismatches: list[str] = []
        for tool_name, expected_args in case.expected_args.items():
            matching_calls = [
                execution for execution in trace.tool_executions if execution.tool_name == tool_name
            ]
            if not matching_calls:
                continue
            if not any(_args_match(execution.arguments, expected_args) for execution in matching_calls):
                mismatches.append(tool_name)
        return mismatches


def _args_match(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            return False
    return True
