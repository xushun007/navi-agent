import json
import tempfile
import unittest
from pathlib import Path

from navi_agent.evolution import EvalSeed, EvalSeedReportStore, EvalSeedReportWriter, EvalSeedStore


class EvalSeedReportTests(unittest.TestCase):
    def test_write_report_creates_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "ifeval_seed.jsonl"
            seed_path.write_text(
                json.dumps(
                    {
                        "key": 1,
                        "prompt": "p1",
                        "instruction_id_list": [],
                        "kwargs": [],
                        "session_id": "s1",
                        "output": "o1",
                        "pass_fail": True,
                        "notes": "ok",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            seed_store = EvalSeedStore(seed_path)
            writer = EvalSeedReportWriter(Path(tmpdir) / "reports")

            report_dir = writer.write_report(seed_store=seed_store)
            payload = json.loads((report_dir / "run.json").read_text(encoding="utf-8"))
            report_md = (report_dir / "REPORT.md").read_text(encoding="utf-8")

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["passed_count"], 1)
        self.assertIn("# Eval seed report", report_md)
        self.assertIn("pass rate", report_md)

    def test_report_store_loads_latest_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "reports"
            writer = EvalSeedReportWriter(root)
            seed_store = EvalSeedStore(Path(tmpdir) / "ifeval_seed.jsonl")
            seed_store._path.write_text(
                json.dumps(
                    {
                        "key": 1,
                        "prompt": "p1",
                        "instruction_id_list": [],
                        "kwargs": [],
                        "session_id": "s1",
                        "output": "o1",
                        "pass_fail": False,
                        "notes": "bad",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            writer.write_report(seed_store=seed_store)

            latest = EvalSeedReportStore(root).get_latest()

        self.assertIsNotNone(latest)
        self.assertEqual(latest.count, 1)
        self.assertEqual(latest.passed_count, 0)
        self.assertEqual(latest.failed_count, 1)


if __name__ == "__main__":
    unittest.main()
