from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import EvolutionCandidate, PromptOverlayStore


class PromptOverlayStoreTests(unittest.TestCase):
    def test_append_candidate_persists_and_lists_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PromptOverlayStore(
                Path(tmpdir) / "prompt-overlay.md",
                Path(tmpdir) / "snapshots",
            )
            candidate = EvolutionCandidate(
                target="prompt",
                summary="Review prompt",
                rationale="Need better final answer",
                metadata={
                    "workflow_name": "agent-healthcheck",
                    "source_session_id": "source-1",
                    "replay_session_id": "replay-1",
                },
            )

            store.append_candidate(candidate)
            text = store.get()
            ids = store.list_candidate_ids()
            count = store.candidate_count()
            workflow_names = store.list_workflow_names()
            source_session_ids = store.list_source_session_ids()
            replay_session_ids = store.list_replay_session_ids()
            entries = store.list_entries()
            grouped_entries = store.list_entries_by_workflow()

        self.assertIsNotNone(text)
        self.assertIn(candidate.candidate_id, text)
        self.assertIn("workflow: agent-healthcheck", text or "")
        self.assertIn("source session: source-1", text or "")
        self.assertIn("replay session: replay-1", text or "")
        self.assertEqual(ids, [candidate.candidate_id])
        self.assertEqual(count, 1)
        self.assertEqual(workflow_names, ["agent-healthcheck"])
        self.assertEqual(source_session_ids, ["source-1"])
        self.assertEqual(replay_session_ids, ["replay-1"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].workflow_name, "agent-healthcheck")
        self.assertEqual(entries[0].source_session_id, "source-1")
        self.assertEqual(entries[0].replay_session_id, "replay-1")
        self.assertEqual(list(grouped_entries), ["agent-healthcheck"])
        self.assertEqual(grouped_entries["agent-healthcheck"][0].candidate_id, candidate.candidate_id)

    def test_snapshot_and_rollback_restore_previous_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PromptOverlayStore(
                Path(tmpdir) / "prompt-overlay.md",
                Path(tmpdir) / "snapshots",
            )
            first = EvolutionCandidate(
                target="prompt",
                summary="First",
                rationale="r1",
            )
            second = EvolutionCandidate(
                target="prompt",
                summary="Second",
                rationale="r2",
            )

            store.append_candidate(first)
            snapshot = store.snapshot(candidate_id=first.candidate_id)
            store.append_candidate(second)
            restored = store.rollback(snapshot.snapshot_id if snapshot is not None else "")
            current = store.get()
            snapshots = store.list_snapshots()

            self.assertIsNotNone(snapshot)
            self.assertIsNotNone(restored)
            self.assertEqual(current, restored)
            self.assertIn(first.candidate_id, restored or "")
            self.assertNotIn(second.candidate_id, restored or "")
            self.assertEqual(len(snapshots), 2)


if __name__ == "__main__":
    unittest.main()
