from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from navi_agent.runtime import (
    AgentRuntime,
    ContextEngine,
    InMemorySessionStore,
    PromptBuilder,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    ModelResponse,
    build_transport,
)
from navi_agent.runtime.tool_policy import SensitiveToolPolicy
from navi_agent.config import ModelSettings, RuntimeSettings, load_config
from navi_agent.memory import InMemoryMemoryStore
from navi_agent.telemetry import RuntimeTrace
from navi_agent.telemetry import InMemoryTraceStore
from navi_agent.tooling import ToolResult
from navi_agent.tools.defaults import build_default_tool_registry


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
    approval_required_tools: list[str] = field(default_factory=list)
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
                    approval_required_tools=list(payload.get("approval_required_tools") or []),
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
    def evaluate(
        self,
        case: ToolUseEvalCase,
        trace: RuntimeTrace,
        *,
        state: dict[str, Any] | None = None,
    ) -> ToolUseEvalResult:
        tool_calls = list(trace.tool_executions)
        tool_names = [execution.tool_name for execution in tool_calls]
        missing_tools = [tool for tool in case.required_tools if tool not in tool_names]
        forbidden_tools = [tool for tool in case.forbidden_tools if tool in tool_names]
        arg_mismatches = self._arg_mismatches(case, trace)
        approval_tools = [
            execution.tool_name for execution in trace.tool_executions if execution.approval_required
        ]
        missing_approvals = [
            tool for tool in case.approval_required_tools if tool not in approval_tools
        ]
        unexpected_approvals = [
            tool for tool in approval_tools if tool not in case.approval_required_tools
        ]
        non_approval_error_count = sum(
            1
            for execution in trace.tool_executions
            if execution.status == "error" and not execution.approval_required
        )
        signals: list[str] = []

        if trace.status != "success":
            signals.append(f"status:{trace.status}")
        if missing_tools:
            signals.append(f"missing_tools:{','.join(missing_tools)}")
        if forbidden_tools:
            signals.append(f"forbidden_tools:{','.join(forbidden_tools)}")
        if arg_mismatches:
            signals.append(f"arg_mismatches:{','.join(arg_mismatches)}")
        if missing_approvals:
            signals.append(f"missing_approvals:{','.join(missing_approvals)}")
        if unexpected_approvals:
            signals.append(f"unexpected_approvals:{','.join(unexpected_approvals)}")
        if trace.total_iterations > case.max_iterations:
            signals.append(f"iterations:{trace.total_iterations}>{case.max_iterations}")
        if non_approval_error_count:
            signals.append(f"tool_errors:{non_approval_error_count}")
        if not trace.final_response.strip():
            signals.append("empty_response")

        state_signals = self._state_signals(case, state)
        signals.extend(state_signals)

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
                "expected_args": dict(case.expected_args),
                "missing_tools": missing_tools,
                "forbidden_tool_hits": forbidden_tools,
                "arg_mismatches": arg_mismatches,
                "approval_required_tools": list(case.approval_required_tools),
                "approval_tools": approval_tools,
                "missing_approvals": missing_approvals,
                "unexpected_approvals": unexpected_approvals,
                "total_iterations": trace.total_iterations,
                "error_count": non_approval_error_count,
                "status": trace.status,
                "grader": case.grader,
                "state": state or {},
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
            elif signal.startswith("missing_approvals:"):
                score -= 0.35
            elif signal.startswith("unexpected_approvals:"):
                score -= 0.2
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

    @staticmethod
    def _state_signals(case: ToolUseEvalCase, state: dict[str, Any] | None) -> list[str]:
        if case.grader != "state_contains":
            return []
        expected = case.expected_outcome.strip()
        if not expected:
            return ["state_missing_expected_outcome"]
        if not state:
            return ["state_missing"]
        haystacks = []
        for value in state.values():
            if isinstance(value, list):
                haystacks.extend(str(item) for item in value)
            else:
                haystacks.append(str(value))
        if any(expected in haystack for haystack in haystacks):
            return []
        return ["state_mismatch"]


def _args_match(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            return False
    return True


@dataclass(slots=True)
class ToolUseRunSummary:
    count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    results: list[ToolUseEvalResult]
    metrics: dict[str, float | int] = field(default_factory=dict)
    report_path: Path | None = None


class ToolUseWorkflowService:
    def __init__(
        self,
        *,
        case_store: ToolUseEvalCaseStore,
        report_root: Path,
        evaluator: ToolUseEvaluator | None = None,
    ) -> None:
        self._case_store = case_store
        self._report_root = report_root
        self._evaluator = evaluator or ToolUseEvaluator()

    def run(self) -> ToolUseRunSummary:
        cases = self._case_store.list_cases()
        results = [self._run_case(case) for case in cases]
        summary = _summarize_tool_use_results(results)
        report_path = ToolUseRunWriter(self._report_root).write_run_report(
            case_store=self._case_store,
            summary=summary,
        )
        summary.report_path = report_path
        return summary

    def _run_case(self, case: ToolUseEvalCase) -> ToolUseEvalResult:
        trace_store = InMemoryTraceStore()
        shared_memory_store = InMemoryMemoryStore()
        transport = _ScriptedToolUseTransport(case)
        runtime = AgentRuntime(
            transport=transport,
            prompt_builder=PromptBuilder(memory_store=shared_memory_store),
            tool_registry=_build_tool_registry(case, memory_store=shared_memory_store),
            session_store=InMemorySessionStore(),
            trace_store=trace_store,
            context_engine=ContextEngine(),
            max_iterations=case.max_iterations,
        )
        session_id = f"tool-use:{case.id}"
        runtime.run_conversation(
            session_id=session_id,
            user_id="tool-use-eval",
            user_message=case.prompt,
        )
        trace = trace_store.get_latest_trace(session_id=session_id, user_id="tool-use-eval")
        if trace is None:
            return ToolUseEvalResult(
                case_id=case.id,
                level=case.level,
                passed=False,
                score=0.0,
                summary="missing runtime trace",
                metadata={"category": case.category, "source_inspiration": case.source_inspiration},
            )
        state = {
            "memory": [
                record.content for record in shared_memory_store.list_for_user("tool-use-eval")
            ]
        }
        return self._evaluator.evaluate(case, trace, state=state)


class ToolUseEvalWorkflowService:
    def __init__(
        self,
        *,
        case_store: ToolUseEvalCaseStore,
        report_root: Path,
        evaluator: ToolUseEvaluator | None = None,
        model_settings: ModelSettings | None = None,
        runtime_settings: RuntimeSettings | None = None,
    ) -> None:
        self._case_store = case_store
        self._report_root = report_root
        self._evaluator = evaluator or ToolUseEvaluator()
        self._model_settings = model_settings
        self._runtime_settings = runtime_settings

    def run(self) -> ToolUseRunSummary:
        cases = self._case_store.list_cases()
        results = [self._run_case(case) for case in cases]
        summary = _summarize_tool_use_results(results)
        report_path = ToolUseRunWriter(self._report_root).write_run_report(
            case_store=self._case_store,
            summary=summary,
        )
        summary.report_path = report_path
        return summary

    def _run_case(self, case: ToolUseEvalCase) -> ToolUseEvalResult:
        config = load_config()
        model_settings = self._model_settings or ModelSettings.from_sources(config)
        runtime_settings = self._runtime_settings or RuntimeSettings.from_sources(config)
        shared_memory_store = InMemoryMemoryStore()
        trace_store = InMemoryTraceStore()
        max_iterations = case.max_iterations if case.max_iterations > 0 else runtime_settings.max_iterations
        runtime = AgentRuntime(
            transport=build_transport(model_settings),
            session_store=InMemorySessionStore(),
            prompt_builder=PromptBuilder(memory_store=shared_memory_store),
            trace_store=trace_store,
            tool_registry=build_default_tool_registry(
                memory_store=shared_memory_store,
            ),
            context_engine=ContextEngine(),
            max_iterations=max_iterations,
        )
        session_id = f"tool-use-eval:{case.id}"
        runtime.run_conversation(
            session_id=session_id,
            user_id="tool-use-eval",
            user_message=case.prompt,
        )
        trace = trace_store.get_latest_trace(session_id=session_id, user_id="tool-use-eval")
        if trace is None:
            return ToolUseEvalResult(
                case_id=case.id,
                level=case.level,
                passed=False,
                score=0.0,
                summary="missing runtime trace",
                metadata={"category": case.category, "source_inspiration": case.source_inspiration},
            )
        state = {
            "memory": [
                record.content for record in shared_memory_store.list_for_user("tool-use-eval")
            ]
        }
        return self._evaluator.evaluate(case, trace, state=state)


class ToolUseRunWriter:
    def __init__(self, report_root: Path) -> None:
        self._report_root = report_root

    def write_run_report(self, *, case_store: ToolUseEvalCaseStore, summary: ToolUseRunSummary) -> Path:
        run_dir = self._new_run_dir()
        payload = {
            "case_path": str(case_store.path),
            "count": summary.count,
            "passed_count": summary.passed_count,
            "failed_count": summary.failed_count,
            "pass_rate": summary.pass_rate,
            "metrics": dict(summary.metrics),
            "results": [asdict(result) for result in summary.results],
        }
        (run_dir / "run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (run_dir / "REPORT.md").write_text(self._render_markdown(payload), encoding="utf-8")
        return run_dir

    def _new_run_dir(self) -> Path:
        from datetime import datetime

        self._report_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = self._report_root / timestamp
        suffix = 1
        while run_dir.exists():
            suffix += 1
            run_dir = self._report_root / f"{timestamp}-{suffix}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    @staticmethod
    def _render_markdown(payload: dict[str, Any]) -> str:
        lines = [
            "# Tool Use Eval Report",
            "",
            f"- case path: `{payload['case_path']}`",
            f"- count: {payload['count']}",
            f"- passed: {payload['passed_count']}",
            f"- failed: {payload['failed_count']}",
            f"- pass rate: {payload['pass_rate']}",
            "",
            "## Metrics",
            "",
        ]
        for key, value in payload.get("metrics", {}).items():
            lines.append(f"- {key}: {value}")
        lines.extend(
            [
                "",
                "## Results",
                "",
            ]
        )
        for result in payload["results"]:
            status = "pass" if result["passed"] else "fail"
            lines.extend(
                [
                    f"- `{result['case_id']}` [{status}] score={result['score']}",
                    f"  - level: {result['level']}",
                    f"  - summary: {result['summary']}",
                ]
            )
        return "\n".join(lines).strip() + "\n"


def _summarize_tool_use_results(results: list[ToolUseEvalResult]) -> ToolUseRunSummary:
    passed_count = sum(1 for result in results if result.passed)
    failed_count = len(results) - passed_count
    pass_rate = round(passed_count / len(results), 3) if results else 0.0
    return ToolUseRunSummary(
        count=len(results),
        passed_count=passed_count,
        failed_count=failed_count,
        pass_rate=pass_rate,
        results=results,
        metrics=_build_tool_use_metrics(results),
    )


def _build_tool_use_metrics(results: list[ToolUseEvalResult]) -> dict[str, float | int]:
    if not results:
        return {
            "average_score": 0.0,
            "tool_selection_accuracy": 0.0,
            "required_tool_recall": 0.0,
            "forbidden_tool_clean_rate": 0.0,
            "arg_match_rate": 0.0,
            "approval_policy_accuracy": 0.0,
            "tool_error_count": 0,
        }

    required_total = 0
    missing_total = 0
    forbidden_total = 0
    forbidden_hit_total = 0
    expected_arg_total = 0
    arg_mismatch_total = 0
    tool_selection_clean_cases = 0
    approval_clean_cases = 0
    tool_error_count = 0

    for result in results:
        metadata = result.metadata
        required_tools = list(metadata.get("required_tools") or [])
        missing_tools = list(metadata.get("missing_tools") or [])
        forbidden_tools = list(metadata.get("forbidden_tools") or [])
        forbidden_hits = list(metadata.get("forbidden_tool_hits") or [])
        arg_mismatches = list(metadata.get("arg_mismatches") or [])
        missing_approvals = list(metadata.get("missing_approvals") or [])
        unexpected_approvals = list(metadata.get("unexpected_approvals") or [])

        required_total += len(required_tools)
        missing_total += len(missing_tools)
        forbidden_total += len(forbidden_tools)
        forbidden_hit_total += len(forbidden_hits)
        expected_args = metadata.get("expected_args")
        if isinstance(expected_args, dict):
            expected_arg_total += len(expected_args)
        arg_mismatch_total += len(arg_mismatches)
        tool_error_count += int(metadata.get("error_count") or 0)

        if not missing_tools and not forbidden_hits:
            tool_selection_clean_cases += 1
        if not missing_approvals and not unexpected_approvals:
            approval_clean_cases += 1

    return {
        "average_score": _ratio(sum(result.score for result in results), len(results)),
        "tool_selection_accuracy": _ratio(tool_selection_clean_cases, len(results)),
        "required_tool_recall": _ratio(required_total - missing_total, required_total),
        "forbidden_tool_clean_rate": _ratio(forbidden_total - forbidden_hit_total, forbidden_total),
        "arg_match_rate": _ratio(expected_arg_total - arg_mismatch_total, expected_arg_total),
        "approval_policy_accuracy": _ratio(approval_clean_cases, len(results)),
        "tool_error_count": tool_error_count,
    }


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 3)


class ToolUseRunStore:
    def __init__(self, report_root: Path) -> None:
        self._report_root = report_root

    def get_latest(self) -> dict[str, Any] | None:
        if not self._report_root.exists():
            return None
        run_dirs = [
            path for path in self._report_root.iterdir() if path.is_dir() and (path / "run.json").exists()
        ]
        if not run_dirs:
            return None
        run_dirs.sort(key=lambda path: path.name, reverse=True)
        payload = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
        payload["report_path"] = str(run_dirs[0])
        return payload


class _ScriptedToolUseTransport:
    def __init__(self, case: ToolUseEvalCase) -> None:
        self._case = case
        self._called = False

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._called:
            return ModelResponse(content=f"Tool use eval completed for {self._case.id}.")
        self._called = True
        tool_calls = [
            ToolCall(
                id=f"tooluse-{index}",
                name=tool_name,
                arguments=dict(self._case.expected_args.get(tool_name) or {}),
            )
            for index, tool_name in enumerate(self._case.required_tools, start=1)
        ]
        if not tool_calls:
            return ModelResponse(content=f"No tool required for {self._case.id}.")
        return ModelResponse(tool_calls=tool_calls)


def _build_tool_registry(
    case: ToolUseEvalCase,
    *,
    memory_store: InMemoryMemoryStore | None = None,
) -> ToolRegistry:
    tool_names = sorted(set(case.required_tools) | set(case.forbidden_tools) | set(case.expected_args))
    definitions = []
    for tool_name in tool_names:
        if tool_name == "memory" and memory_store is not None:
            definitions.append(
                ToolDefinition(
                    name="memory",
                    description="Fake memory tool-use eval tool",
                    parameters={
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                    handler=_fake_memory_handler(case=case, memory_store=memory_store),
                )
            )
            continue
        definitions.append(
            ToolDefinition(
                name=tool_name,
                description=f"Fake tool-use eval tool: {tool_name}",
                parameters={"type": "object", "properties": {}, "additionalProperties": True},
                handler=_fake_tool_handler(tool_name),
            )
        )
    return ToolRegistry(
        definitions=definitions,
        policy=SensitiveToolPolicy(
            approval_required_tools={
                tool_name: f"Tool use eval requires approval for {tool_name}"
                for tool_name in case.approval_required_tools
            }
        ),
    )


def _fake_tool_handler(tool_name: str):
    def handler(**kwargs) -> ToolResult:
        return ToolResult.ok(
            name=tool_name,
            content=json.dumps(
                {"tool": tool_name, "arguments": kwargs, "status": "ok"},
                ensure_ascii=False,
                sort_keys=True,
            ),
            structured_content={"arguments": kwargs},
        )

    return handler


def _fake_memory_handler(
    *,
    case: ToolUseEvalCase,
    memory_store: InMemoryMemoryStore,
):
    def handler(*, context=None, action: str, content: str = "") -> ToolResult:
        if context is None:
            return ToolResult.error(name="memory", content="memory_error: missing tool context")
        if action == "add":
            memory_content = content.strip() or case.expected_outcome.strip() or case.prompt.strip()
            if memory_content:
                memory_store.add_for_user(context.user_id, memory_content)
                return ToolResult.ok(
                    name="memory",
                    content="memory_stored",
                    structured_content={"user_id": context.user_id, "content": memory_content},
                )
            return ToolResult.error(name="memory", content="memory_error: content is required for add")
        if action == "list":
            records = memory_store.list_for_user(context.user_id)
            return ToolResult.ok(
                name="memory",
                content="\n".join(f"- {record.content}" for record in records) if records else "memory_empty",
                structured_content={"records": [record.content for record in records]},
            )
        return ToolResult.error(name="memory", content=f"memory_error: unsupported action '{action}'")

    return handler
