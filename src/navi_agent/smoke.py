from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from navi_agent.doctor import collect_report
from navi_agent.memory import InMemoryMemoryStore
from navi_agent.paths import get_smoke_reports_dir
from navi_agent.runtime import (
    AgentRuntime,
    ContextEngine,
    DemoTransport,
    InMemorySessionStore,
    ModelResponse,
    PromptBuilder,
    ToolCall,
)
from navi_agent.telemetry import InMemoryTraceStore
from navi_agent.tools.defaults import build_default_tool_registry


@dataclass(slots=True)
class SmokeCheckResult:
    name: str
    passed: bool
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SmokeRunSummary:
    count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    results: list[SmokeCheckResult]
    report_path: Path | None = None


class SmokeWorkflowService:
    def __init__(self, *, report_root: Path | None = None) -> None:
        self._report_root = report_root or get_smoke_reports_dir()

    def run(self) -> SmokeRunSummary:
        results = [
            self._doctor_check(),
            self._demo_runtime_check(),
            self._tool_runtime_check(),
        ]
        passed_count = sum(1 for result in results if result.passed)
        failed_count = len(results) - passed_count
        summary = SmokeRunSummary(
            count=len(results),
            passed_count=passed_count,
            failed_count=failed_count,
            pass_rate=round(passed_count / len(results), 3) if results else 0.0,
            results=results,
        )
        summary.report_path = SmokeRunWriter(self._report_root).write_run_report(summary)
        return summary

    def _doctor_check(self) -> SmokeCheckResult:
        report = collect_report()
        passed = report.ok
        summary = "doctor ok" if passed else "doctor failed"
        return SmokeCheckResult(
            name="doctor",
            passed=passed,
            summary=summary,
            metadata={"lines": report.lines},
        )

    def _demo_runtime_check(self) -> SmokeCheckResult:
        trace_store = InMemoryTraceStore()
        memory_store = InMemoryMemoryStore()
        runtime = AgentRuntime(
            transport=DemoTransport(),
            session_store=InMemorySessionStore(),
            prompt_builder=PromptBuilder(memory_store=memory_store),
            trace_store=trace_store,
            tool_registry=build_default_tool_registry(memory_store=memory_store),
            context_engine=ContextEngine(),
            max_iterations=3,
        )
        session_id = "smoke-demo"
        result = runtime.run_conversation(
            session_id=session_id,
            user_id="smoke",
            user_message="hello smoke",
        )
        trace = trace_store.get_latest_trace(session_id=session_id, user_id="smoke")
        passed = (
            result.status == "success"
            and "Demo mode is active." in result.final_response
            and trace is not None
        )
        summary = "demo runtime ok" if passed else "demo runtime failed"
        return SmokeCheckResult(
            name="runtime_demo",
            passed=passed,
            summary=summary,
            metadata={
                "status": result.status,
                "final_response": result.final_response,
                "trace_id": trace.trace_id if trace is not None else None,
            },
        )

    def _tool_runtime_check(self) -> SmokeCheckResult:
        trace_store = InMemoryTraceStore()
        memory_store = InMemoryMemoryStore()
        runtime = AgentRuntime(
            transport=_ScriptedSmokeTransport(),
            session_store=InMemorySessionStore(),
            prompt_builder=PromptBuilder(memory_store=memory_store),
            trace_store=trace_store,
            tool_registry=build_default_tool_registry(memory_store=memory_store),
            context_engine=ContextEngine(),
            max_iterations=3,
        )
        session_id = "smoke-tool"
        result = runtime.run_conversation(
            session_id=session_id,
            user_id="smoke",
            user_message="请记录一个待办",
        )
        trace = trace_store.get_latest_trace(session_id=session_id, user_id="smoke")
        tool_names = [execution.tool_name for execution in trace.tool_executions] if trace else []
        passed = result.status == "success" and "todo" in tool_names and trace is not None
        summary = "tool runtime ok" if passed else "tool runtime failed"
        return SmokeCheckResult(
            name="runtime_tool",
            passed=passed,
            summary=summary,
            metadata={
                "status": result.status,
                "tool_names": tool_names,
                "trace_id": trace.trace_id if trace is not None else None,
                "memory": [record.content for record in memory_store.list_for_user("smoke")],
            },
        )


class SmokeRunWriter:
    def __init__(self, report_root: Path) -> None:
        self._report_root = report_root

    def write_run_report(self, summary: SmokeRunSummary) -> Path:
        run_dir = self._new_run_dir()
        payload = {
            "count": summary.count,
            "passed_count": summary.passed_count,
            "failed_count": summary.failed_count,
            "pass_rate": summary.pass_rate,
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
            "# Smoke Workflow Report",
            "",
            f"- count: {payload['count']}",
            f"- passed: {payload['passed_count']}",
            f"- failed: {payload['failed_count']}",
            f"- pass rate: {payload['pass_rate']}",
            "",
            "## Results",
            "",
        ]
        for result in payload["results"]:
            status = "pass" if result["passed"] else "fail"
            lines.extend(
                [
                    f"- `{result['name']}` [{status}]",
                    f"  - summary: {result['summary']}",
                ]
            )
        return "\n".join(lines).strip() + "\n"


class SmokeRunStore:
    def __init__(self, report_root: Path | None = None) -> None:
        self._report_root = report_root or get_smoke_reports_dir()

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


class _ScriptedSmokeTransport:
    def __init__(self) -> None:
        self._called = False

    def generate(self, request):
        if self._called:
            return ModelResponse(content="smoke tool flow complete")
        self._called = True
        return ModelResponse(
            tool_calls=[
                ToolCall(
                    id="smoke-todo-1",
                    name="todo",
                    arguments={
                        "action": "add",
                        "content": "smoke workflow sanity",
                        "status": "pending",
                    },
                )
            ]
        )
