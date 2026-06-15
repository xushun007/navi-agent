from __future__ import annotations

from navi_agent.telemetry import RuntimeTrace

from .models import EvaluationResult, EvolutionCandidate
from .store import CandidateStore


class SimpleEvaluator:
    def evaluate(self, trace: RuntimeTrace) -> EvaluationResult:
        score = 1.0
        signals: list[str] = []
        duplicate_tool_count = self._duplicate_tool_count(trace)

        if trace.status != "success":
            score -= 0.5
            signals.append(f"status:{trace.status}")
        if trace.error_count:
            score -= min(0.3, trace.error_count * 0.1)
            signals.append(f"tool_errors:{trace.error_count}")
        if trace.approval_count:
            score -= min(0.2, trace.approval_count * 0.1)
            signals.append(f"approvals:{trace.approval_count}")
        if not trace.final_response.strip():
            score -= 0.2
            signals.append("empty_response")
        if trace.total_iterations > 3:
            score -= 0.1
            signals.append(f"iterations:{trace.total_iterations}")
        if duplicate_tool_count:
            score -= min(0.15, duplicate_tool_count * 0.05)
            signals.append(f"duplicate_tools:{duplicate_tool_count}")
        if trace.duration_ms >= 30_000:
            score -= 0.1
            signals.append(f"duration_ms:{trace.duration_ms}")

        score = max(0.0, round(score, 3))
        summary = self._build_summary(trace, signals)
        return EvaluationResult(
            session_id=trace.session_id,
            score=score,
            summary=summary,
            metadata={
                "tool_names": list(trace.tool_names),
                "status": trace.status,
                "error_count": trace.error_count,
                "approval_count": trace.approval_count,
                "total_iterations": trace.total_iterations,
                "duplicate_tool_count": duplicate_tool_count,
                "duration_ms": trace.duration_ms,
                "has_final_response": bool(trace.final_response.strip()),
                "signals": signals,
            },
        )

    def build_candidate(self, evaluation: EvaluationResult) -> EvolutionCandidate | None:
        if evaluation.score >= 1.0:
            return None
        target = "prompt"
        if evaluation.metadata.get("approval_count", 0):
            target = "tool_policy"
        elif evaluation.metadata.get("error_count", 0):
            target = "tooling"
        elif not evaluation.metadata.get("has_final_response", True):
            target = "prompt"
        elif evaluation.metadata.get("duplicate_tool_count", 0):
            target = "tooling"
        elif evaluation.metadata.get("status") == "iteration_limit_exceeded":
            target = "prompt"
        return EvolutionCandidate(
            target=target,
            summary=f"Review underperforming runtime session ({target})",
            rationale=evaluation.summary,
            metadata={
                "session_id": evaluation.session_id,
                "signals": list(evaluation.metadata.get("signals", [])),
            },
        )

    def store_candidate(
        self,
        candidate_store: CandidateStore,
        candidate: EvolutionCandidate | None,
    ) -> None:
        if candidate is None:
            return
        candidate_store.add(candidate)

    def _build_summary(self, trace: RuntimeTrace, signals: list[str]) -> str:
        if not signals:
            return "Successful run with no obvious issues"
        if trace.status == "iteration_limit_exceeded":
            return "Run hit the iteration limit before finishing"
        if trace.approval_count:
            return "Run was blocked by approval-gated tool usage"
        if trace.error_count:
            return "Run encountered tool execution errors"
        if not trace.final_response.strip():
            return "Run completed without a final answer"
        if self._duplicate_tool_count(trace):
            return "Run repeated tool usage and may be wasting steps"
        if trace.duration_ms >= 30_000:
            return "Run completed but took longer than expected"
        if trace.status != "success":
            return f"Run ended with status {trace.status}"
        return "Run completed with inefficiencies that should be reviewed"

    @staticmethod
    def _duplicate_tool_count(trace: RuntimeTrace) -> int:
        tool_names = [execution.tool_name for execution in trace.tool_executions]
        if not tool_names:
            return 0
        return max(0, len(tool_names) - len(set(tool_names)))
