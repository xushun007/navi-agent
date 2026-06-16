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
            )

            store.append_candidate(candidate)
            text = store.get()
            ids = store.list_candidate_ids()
            count = store.candidate_count()

        self.assertIsNotNone(text)
        self.assertIn(candidate.candidate_id, text)
        self.assertEqual(ids, [candidate.candidate_id])
        self.assertEqual(count, 1)

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
