import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import (
    EvolutionCandidate,
    JsonlCandidateStore,
    JsonlWorkflowSampleStore,
    WorkflowEvolutionSample,
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

    def test_workflow_sample_store_persists_and_lists_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlWorkflowSampleStore(Path(tmpdir) / "samples.jsonl")
            store.add(
                WorkflowEvolutionSample(
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
