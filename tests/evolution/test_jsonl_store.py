import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import (
    EvolutionCandidate,
    JsonlCandidateStore,
    JsonlEvalCaseStore,
    EvalCase,
)


class JsonlStoreTests(unittest.TestCase):
    def test_candidate_store_persists_and_lists_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlCandidateStore(Path(tmpdir) / "candidates.jsonl")
            store.add(
                EvolutionCandidate(
                    target="prompt",
                    summary="first",
                    rationale="r1",
                )
            )
            store.add(
                EvolutionCandidate(
                    target="tooling",
                    summary="second",
                    rationale="r2",
                )
            )

            items = store.list_recent(limit=1)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].summary, "second")
        self.assertEqual(items[0].status, "pending")

    def test_candidate_store_updates_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlCandidateStore(Path(tmpdir) / "candidates.jsonl")
            candidate = EvolutionCandidate(
                target="prompt",
                summary="first",
                rationale="r1",
            )
            store.add(candidate)

            updated = store.update_status(candidate.candidate_id, "accepted", review_note="looks good")
            latest = store.get(candidate.candidate_id)

        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "accepted")
        self.assertEqual(updated.review_note, "looks good")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.status, "accepted")

    def test_eval_case_store_persists_and_lists_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlEvalCaseStore(Path(tmpdir) / "eval-cases.jsonl")
            store.add(
                EvalCase(
                    workflow_name="wf",
                    source_session_id="s1",
                    replay_session_id="s2",
                    source_average_score=1.0,
                    replay_average_score=0.9,
                    score_delta=-0.1,
                    status="regressed",
                    summary="regressed",
                )
            )

            items = store.list_recent(limit=10)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, "regressed")


if __name__ == "__main__":
    unittest.main()
