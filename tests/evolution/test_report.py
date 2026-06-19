from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from navi_agent.evolution import EvolutionReportStore, EvolutionReportWriter, ReviewLoopSummary
from navi_agent.evolution.models import EvaluationResult, EvolutionCandidate, WorkflowEvolutionSample
from navi_agent.runtime import RuntimeResult
from navi_agent.smoke import (
    SmokeStepComparison,
    SmokeStepResult,
    SmokeWorkflow,
    SmokeWorkflowComparison,
)
from navi_agent.telemetry import RuntimeTrace


class EvolutionReportWriterTests(unittest.TestCase):
    def test_write_workflow_comparison_report_creates_json_and_markdown(self) -> None:
        comparison = SmokeWorkflowComparison(
            workflow_name="prototype-baseline",
            source_session_id="wf-1",
            replay_session_id="wf-2",
            step_comparisons=[
                SmokeStepComparison(
                    task_name="config-check",
                    source_step=SmokeStepResult(
                        task_name="config-check",
                        runtime_result=RuntimeResult(session_id="wf-1", status="success", final_response="source"),
                        trace=RuntimeTrace(
                            session_id="wf-1",
                            user_id="u1",
                            user_message="prompt",
                            final_response="source",
                            status="success",
                            trace_id="trace-1",
                        ),
                    ),
                    replay_step=SmokeStepResult(
                        task_name="config-check",
                        runtime_result=RuntimeResult(session_id="wf-2", status="success", final_response="replay"),
                        trace=RuntimeTrace(
                            session_id="wf-2",
                            user_id="u1",
                            user_message="prompt",
                            final_response="replay",
                            status="success",
                            trace_id="trace-2",
                        ),
                    ),
                    source_evaluation=EvaluationResult(session_id="wf-1", score=1.0, summary="source ok"),
                    replay_evaluation=EvaluationResult(session_id="wf-2", score=0.8, summary="replay slower"),
                    score_delta=-0.2,
                )
            ],
            source_average_score=1.0,
            replay_average_score=0.8,
            score_delta=-0.2,
            sample=WorkflowEvolutionSample(
                workflow_name="prototype-baseline",
                source_session_id="wf-1",
                replay_session_id="wf-2",
                source_average_score=1.0,
                replay_average_score=0.8,
                score_delta=-0.2,
                status="regressed",
                summary="Workflow replay regressed compared with the source run",
            ),
            candidate=EvolutionCandidate(
                target="prompt",
                summary="Review workflow regression in config-check (prompt)",
                rationale="empty response observed",
            ),
        )
        review_summary = ReviewLoopSummary(
            candidate_count=1,
            pending_candidate_count=1,
            accepted_candidate_count=0,
            rejected_candidate_count=0,
            applied_candidate_count=0,
            verified_candidate_count=0,
            no_improvement_candidate_count=0,
            regressed_after_apply_candidate_count=0,
            workflow_sample_count=2,
            regressed_count=1,
            improved_count=1,
            unchanged_count=0,
            top_candidate_targets=[("prompt", 1)],
            top_regressed_workflows=[("prototype-baseline", 1)],
            recommendation="Prioritize prompt improvements for prototype-baseline based on recent regressions.",
        )

        with TemporaryDirectory() as tmp_dir:
            writer = EvolutionReportWriter(Path(tmp_dir))
            run_dir = writer.write_workflow_comparison_report(
                comparison=comparison,
                review_summary=review_summary,
            )

            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            report_md = (run_dir / "REPORT.md").read_text(encoding="utf-8")

        self.assertEqual(payload["workflow_name"], "prototype-baseline")
        self.assertEqual(payload["candidate"]["target"], "prompt")
        self.assertEqual(payload["candidate"]["status"], "pending")
        self.assertEqual(payload["step_comparisons"][0]["source_trace_id"], "trace-1")
        self.assertEqual(payload["review_summary"]["regressed_count"], 1)
        self.assertIn("# Evolution workflow comparison", report_md)
        self.assertIn("## Candidate", report_md)
        self.assertIn("prototype-baseline", report_md)

    def test_report_store_loads_latest_report(self) -> None:
        comparison = SmokeWorkflowComparison(
            workflow_name="prototype-baseline",
            source_session_id="wf-1",
            replay_session_id="wf-2",
            step_comparisons=[],
            source_average_score=1.0,
            replay_average_score=0.8,
            score_delta=-0.2,
            sample=WorkflowEvolutionSample(
                workflow_name="prototype-baseline",
                source_session_id="wf-1",
                replay_session_id="wf-2",
                source_average_score=1.0,
                replay_average_score=0.8,
                score_delta=-0.2,
                status="regressed",
                summary="regressed",
            ),
            candidate=EvolutionCandidate(
                target="prompt",
                summary="candidate",
                rationale="rationale",
            ),
        )
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            writer = EvolutionReportWriter(root)
            writer.write_workflow_comparison_report(comparison=comparison)

            latest = EvolutionReportStore(root).get_latest()

        self.assertIsNotNone(latest)
        self.assertEqual(latest.workflow_name, "prototype-baseline")
        self.assertEqual(latest.status, "regressed")
        self.assertEqual(latest.candidate_target, "prompt")
        self.assertEqual(latest.candidate_status, "pending")


if __name__ == "__main__":
    unittest.main()
