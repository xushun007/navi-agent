from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import EvolutionCandidate, PromptOverlayStore


class PromptOverlayStoreTests(unittest.TestCase):
    def test_append_candidate_persists_and_lists_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PromptOverlayStore(Path(tmpdir) / "prompt-overlay.md")
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


if __name__ == "__main__":
    unittest.main()
