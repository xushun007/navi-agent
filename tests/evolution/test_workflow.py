import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import EvalSeed
from navi_agent.evolution import EvalSeedStore
from navi_agent.evolution import IfevalWorkflowService

class IfevalWorkflowServiceTests(unittest.TestCase):
    def test_review_latest_draft_promotes_to_seed_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            draft_path = Path(tmpdir) / "ifeval-drafts.jsonl"
            seed_path = Path(tmpdir) / "ifeval_seed.jsonl"
            draft_store = EvalSeedStore(draft_path)
            seed_store = EvalSeedStore(seed_path)
            draft_store.append(
                EvalSeed(
                    key=7,
                    prompt="prompt",
                    instruction_id_list=["punctuation:no_comma"],
                    kwargs=[{}],
                    session_id="session-1",
                    output="answer",
                    pass_fail=None,
                    notes="draft",
                )
            )
            service = IfevalWorkflowService(
                draft_store=draft_store,
                seed_store=seed_store,
                report_root=Path(tmpdir) / "reports",
            )

            result = service.review_latest_draft(confirm_latest_draft=lambda draft: True)
            promoted = EvalSeedStore(seed_path).list_recent(limit=None)
            remaining = EvalSeedStore(draft_path).list_recent(limit=None)

        self.assertTrue(result.promoted)
        self.assertEqual(result.draft_count, 1)
        self.assertIsNotNone(result.draft)
        self.assertEqual(result.draft.key, 7)
        self.assertEqual(remaining, [])
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0].key, 7)

    def test_run_workflow_runs_evaluation_and_reports_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "ifeval_seed.jsonl"
            report_root = Path(tmpdir) / "reports"
            seed_store = EvalSeedStore(seed_path)
            seed_store.append(
                EvalSeed(
                    key=1,
                    prompt="Prompt",
                    instruction_id_list=["punctuation:no_comma"],
                    kwargs=[{}],
                    session_id="session-1",
                    output="answer",
                    pass_fail=None,
                    notes=None,
                )
            )
            service = IfevalWorkflowService(
                seed_store=seed_store,
                report_root=report_root,
                run_seed=lambda seed: (seed.session_id, "hello world"),
            )

            result = service.run()
            report_exists = result.run.report_path.exists() if result.run.report_path else False

        self.assertTrue(result.review.skipped)
        self.assertEqual(result.run.count, 1)
        self.assertFalse(result.run.skipped)
        self.assertIsNotNone(result.run.report_path)
        self.assertTrue(report_exists)
        self.assertIsNotNone(result.status.latest_report)
        self.assertEqual(result.status.latest_report.count, 1)


if __name__ == "__main__":
    unittest.main()
