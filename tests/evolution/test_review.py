import unittest

from navi_agent.evolution import EvolutionCandidate, ReviewLoopService, EvalCase


class ReviewLoopServiceTests(unittest.TestCase):
    def test_summarize_reports_top_targets_and_regressions(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(target="prompt", summary="a", rationale="r"),
                EvolutionCandidate(target="prompt", summary="b", rationale="r", status="accepted"),
                EvolutionCandidate(target="tooling", summary="c", rationale="r", status="rejected"),
            ],
            eval_cases=[
                EvalCase(
                    workflow_name="agent-healthcheck",
                    source_session_id="s1",
                    replay_session_id="r1",
                    source_average_score=1.0,
                    replay_average_score=0.8,
                    score_delta=-0.2,
                    status="regressed",
                    summary="regressed",
                ),
                EvalCase(
                    workflow_name="agent-healthcheck",
                    source_session_id="s2",
                    replay_session_id="r2",
                    source_average_score=1.0,
                    replay_average_score=0.85,
                    score_delta=-0.15,
                    status="regressed",
                    summary="regressed",
                ),
                EvalCase(
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
        self.assertEqual(summary.active_candidate_count, 2)
        self.assertEqual(summary.pending_candidate_count, 1)
        self.assertEqual(summary.accepted_candidate_count, 1)
        self.assertEqual(summary.rejected_candidate_count, 1)
        self.assertEqual(summary.applied_candidate_count, 0)
        self.assertEqual(summary.verified_candidate_count, 0)
        self.assertEqual(summary.no_improvement_candidate_count, 0)
        self.assertEqual(summary.regressed_after_apply_candidate_count, 0)
        self.assertEqual(summary.superseded_candidate_count, 0)
        self.assertEqual(summary.archived_candidate_count, 0)
        self.assertEqual(summary.eval_case_count, 3)
        self.assertEqual(summary.regressed_count, 2)
        self.assertEqual(summary.top_candidate_targets[0], ("prompt", 2))
        self.assertEqual(summary.pending_targets[0], ("prompt", 1))
        self.assertEqual(summary.top_regressed_workflows[0], ("agent-healthcheck", 2))
        self.assertEqual(len(summary.candidates_by_target["prompt"]), 2)
        self.assertIn("Prioritize prompt improvements", summary.recommendation)

    def test_summarize_handles_no_regressions(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[],
            eval_cases=[
                EvalCase(
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
            eval_cases=[],
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
                        "workflow_name": "agent-healthcheck",
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
                        "workflow_name": "agent-healthcheck",
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
            eval_cases=[],
        )

        self.assertEqual(len(summary.pending_queue), 3)
        self.assertEqual(summary.pending_queue[0].summary, "strong regression")
        self.assertEqual(summary.pending_queue[1].summary, "mild regression")
        self.assertEqual(summary.pending_queue[2].summary, "unchanged run")
        self.assertEqual(summary.pending_work_items[0]["summary"], "strong regression")
        self.assertEqual(summary.pending_work_items[0]["workflow_name"], "agent-healthcheck")
        self.assertEqual(summary.pending_work_items[0]["workflow_status"], "regressed")

    def test_summarize_counts_candidate_outcomes(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(target="prompt", summary="v", rationale="r", status="verified"),
                EvolutionCandidate(target="prompt", summary="n", rationale="r", status="no_improvement"),
                EvolutionCandidate(target="prompt", summary="g", rationale="r", status="regressed_after_apply"),
            ],
            eval_cases=[],
        )

        self.assertEqual(summary.verified_candidate_count, 1)
        self.assertEqual(summary.no_improvement_candidate_count, 1)
        self.assertEqual(summary.regressed_after_apply_candidate_count, 1)
        self.assertEqual(summary.active_candidate_count, 0)

    def test_summarize_excludes_rejected_from_active_views(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(target="prompt", summary="pending", rationale="r", status="pending"),
                EvolutionCandidate(target="tooling", summary="reject me", rationale="r", status="rejected"),
            ],
            eval_cases=[],
        )

        self.assertEqual(summary.candidate_count, 2)
        self.assertEqual(summary.active_candidate_count, 1)
        self.assertEqual(summary.rejected_candidate_count, 1)
        self.assertEqual(summary.top_candidate_targets, [("prompt", 1)])
        self.assertEqual(list(summary.candidates_by_target), ["prompt"])

    def test_summarize_excludes_superseded_and_archived_from_active_views(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(target="prompt", summary="pending", rationale="r", status="pending"),
                EvolutionCandidate(target="prompt", summary="old one", rationale="r", status="superseded"),
                EvolutionCandidate(target="tooling", summary="archived one", rationale="r", status="archived"),
            ],
            eval_cases=[],
        )

        self.assertEqual(summary.candidate_count, 3)
        self.assertEqual(summary.active_candidate_count, 1)
        self.assertEqual(summary.superseded_candidate_count, 1)
        self.assertEqual(summary.archived_candidate_count, 1)
        self.assertEqual(summary.pending_targets, [("prompt", 1)])
        self.assertEqual(len(summary.pending_queue), 1)
        self.assertEqual(list(summary.candidates_by_target), ["prompt"])

    def test_summarize_recommends_investigating_regressed_after_apply_first(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(
                    target="prompt",
                    summary="bad apply",
                    rationale="r",
                    status="regressed_after_apply",
                ),
            ],
            eval_cases=[
                EvalCase(
                    workflow_name="agent-healthcheck",
                    source_session_id="s1",
                    replay_session_id="r1",
                    source_average_score=1.0,
                    replay_average_score=0.7,
                    score_delta=-0.3,
                    status="regressed",
                    summary="regressed",
                )
            ],
        )

        self.assertEqual(
            summary.recommendation,
            "Inspect regressed_after_apply candidates before applying more prompt changes to agent-healthcheck.",
        )

    def test_summarize_recommends_promoting_verified_candidates(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(
                    target="prompt",
                    summary="good apply",
                    rationale="r",
                    status="verified",
                ),
            ],
            eval_cases=[],
        )

        self.assertEqual(
            summary.recommendation,
            "Promote verified prompt changes into the baseline before expanding the workflow set.",
        )

    def test_summarize_recommends_replacing_no_improvement_candidates(self) -> None:
        summary = ReviewLoopService().summarize(
            candidates=[
                EvolutionCandidate(
                    target="prompt",
                    summary="flat apply",
                    rationale="r",
                    status="no_improvement",
                ),
            ],
            eval_cases=[],
        )

        self.assertEqual(
            summary.recommendation,
            "Review no_improvement candidates and replace stale prompt overlays before expanding the workflow set.",
        )


if __name__ == "__main__":
    unittest.main()
