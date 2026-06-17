import unittest

from navi_agent.evolution import EvolutionCandidate, ReviewLoopService, WorkflowEvolutionSample


class ReviewLoopServiceTests(unittest.TestCase):
    def test_summarize_reports_top_targets_and_regressions(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(target="prompt", summary="a", rationale="r"),
                EvolutionCandidate(target="prompt", summary="b", rationale="r", status="accepted"),
                EvolutionCandidate(target="tooling", summary="c", rationale="r", status="rejected"),
            ],
            workflow_samples=[
                WorkflowEvolutionSample(
                    workflow_name="prototype-baseline",
                    source_session_id="s1",
                    replay_session_id="r1",
                    source_average_score=1.0,
                    replay_average_score=0.8,
                    score_delta=-0.2,
                    status="regressed",
                    summary="regressed",
                ),
                WorkflowEvolutionSample(
                    workflow_name="prototype-baseline",
                    source_session_id="s2",
                    replay_session_id="r2",
                    source_average_score=1.0,
                    replay_average_score=0.85,
                    score_delta=-0.15,
                    status="regressed",
                    summary="regressed",
                ),
                WorkflowEvolutionSample(
                    workflow_name="product-orientation",
                    source_session_id="s3",
                    replay_session_id="r3",
                    source_average_score=0.8,
                    replay_average_score=0.9,
                    score_delta=0.1,
                    status="improved",
                    summary="improved",
                ),
            ],
        )

        self.assertEqual(summary.candidate_count, 3)
        self.assertEqual(summary.pending_candidate_count, 1)
        self.assertEqual(summary.accepted_candidate_count, 1)
        self.assertEqual(summary.rejected_candidate_count, 1)
        self.assertEqual(summary.applied_candidate_count, 0)
        self.assertEqual(summary.workflow_sample_count, 3)
        self.assertEqual(summary.regressed_count, 2)
        self.assertEqual(summary.top_candidate_targets[0], ("prompt", 2))
        self.assertEqual(summary.pending_targets[0], ("prompt", 1))
        self.assertEqual(summary.top_regressed_workflows[0], ("prototype-baseline", 2))
        self.assertEqual(len(summary.candidates_by_target["prompt"]), 2)
        self.assertIn("Prioritize prompt improvements", summary.recommendation)

    def test_summarize_handles_no_regressions(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[],
            workflow_samples=[
                WorkflowEvolutionSample(
                    workflow_name="product-orientation",
                    source_session_id="s1",
                    replay_session_id="r1",
                    source_average_score=0.8,
                    replay_average_score=0.9,
                    score_delta=0.1,
                    status="improved",
                    summary="improved",
                )
            ],
        )

        self.assertEqual(summary.regressed_count, 0)
        self.assertEqual(
            summary.recommendation,
            "No regressions detected in recent workflow comparisons.",
        )

    def test_summarize_prefers_pending_targets_without_regressions(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(target="tool_policy", summary="a", rationale="r"),
            ],
            workflow_samples=[],
        )

        self.assertEqual(summary.pending_targets[0], ("tool_policy", 1))
        self.assertEqual(
            summary.recommendation,
            "Review pending tool_policy candidates before expanding the workflow set.",
        )

    def test_summarize_orders_pending_queue_by_regression_priority(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(
                    target="prompt",
                    summary="mild regression",
                    rationale="r",
                    metadata={
                        "workflow_name": "prototype-baseline",
                        "workflow_status": "regressed",
                        "workflow_score_delta": -0.1,
                        "step_score_delta": -0.05,
                    },
                ),
                EvolutionCandidate(
                    target="tooling",
                    summary="strong regression",
                    rationale="r",
                    metadata={
                        "workflow_name": "prototype-baseline",
                        "workflow_status": "regressed",
                        "workflow_score_delta": -0.4,
                        "step_score_delta": -0.2,
                    },
                ),
                EvolutionCandidate(
                    target="tool_policy",
                    summary="unchanged run",
                    rationale="r",
                    metadata={
                        "workflow_name": "product-orientation",
                        "workflow_status": "unchanged",
                        "workflow_score_delta": 0.0,
                    },
                ),
            ],
            workflow_samples=[],
        )

        self.assertEqual(len(summary.pending_queue), 3)
        self.assertEqual(summary.pending_queue[0].summary, "strong regression")
        self.assertEqual(summary.pending_queue[1].summary, "mild regression")
        self.assertEqual(summary.pending_queue[2].summary, "unchanged run")


if __name__ == "__main__":
    unittest.main()
