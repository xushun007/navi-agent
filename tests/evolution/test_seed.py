import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import EvalSeed, EvalSeedStore


class EvalSeedStoreTests(unittest.TestCase):
    def test_list_recent_reads_seed_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ifeval_seed.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"key": 1, "prompt": "p1", "instruction_id_list": [], "kwargs": [], "session_id": "s1", "output": "o1", "pass_fail": true, "notes": "ok"}',
                        '{"key": 2, "prompt": "p2", "instruction_id_list": [], "kwargs": [], "session_id": "s2", "output": "o2", "pass_fail": false, "notes": "bad"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            store = EvalSeedStore(path)
            seeds = store.list_recent(limit=1)

        self.assertEqual(len(seeds), 1)
        self.assertIsInstance(seeds[0], EvalSeed)
        self.assertEqual(seeds[0].key, 2)
        self.assertFalse(seeds[0].pass_fail)

    def test_validate_reports_bad_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ifeval_seed.jsonl"
            path.write_text(
                '{"key": "bad", "prompt": "", "instruction_id_list": {}, "kwargs": {}, "session_id": "", "output": 1, "pass_fail": "yes"}\n',
                encoding="utf-8",
            )

            issues = EvalSeedStore(path).validate()

        self.assertGreaterEqual(len(issues), 5)
        self.assertIn("key must be an integer", "\n".join(issues))
        self.assertIn("prompt must be a non-empty string", "\n".join(issues))


if __name__ == "__main__":
    unittest.main()
