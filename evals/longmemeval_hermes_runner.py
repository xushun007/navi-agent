"""Run isolated Hermes LongMemEval workers using the local Navi model settings."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from evals.longmemeval import load_samples
from navi_agent.config import ModelSettings, RuntimeSettings, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, action="append", required=True)
    parser.add_argument("--sample-id", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--range-fragments", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args()
    if args.max_concurrency < 1 or len(set(args.sample_id)) != len(args.sample_id):
        parser.error("Concurrency must be positive and sample IDs must be unique")
    hermes = args.hermes_dir.resolve()
    python = hermes / ".venv/bin/python"
    if not python.is_file():
        parser.error("Hermes Python environment not found")
    samples = {}
    for path in args.dataset:
        for sample in load_samples(path, range_fragment=args.range_fragments)[0]:
            samples[str(sample["question_id"])] = sample
    missing = set(args.sample_id) - samples.keys()
    if missing:
        parser.error(f"Missing sample IDs: {sorted(missing)}")
    config = load_config()
    model = ModelSettings.from_sources(config)
    runtime = RuntimeSettings.from_sources(config)
    if not model.api_key or not model.base_url:
        parser.error("Configure model credentials and base URL")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=hermes, text=True).strip()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    metadata = {"hermes_commit": commit, "model": model.model, "base_url": model.base_url,
                "max_iterations": runtime.max_iterations, "max_concurrency": args.max_concurrency,
                "sample_ids": args.sample_id, "timezone_assumption": "UTC wall time",
                "mode": "historical_session_search_only",
                "input_files": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                for path in args.dataset]}
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    worker = Path(__file__).with_name("longmemeval_hermes.py").resolve()

    def run(question_id: str) -> tuple[str, int]:
        folder = (args.output_dir / question_id).resolve()
        folder.mkdir()
        sample_path = folder / "sample.json"
        sample_path.write_text(json.dumps(samples[question_id], ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        env.update(HERMES_HOME=str(folder / "home"), PILOT_BASE_URL=model.base_url, PILOT_API_KEY=model.api_key,
                   PILOT_MODEL=model.model, PILOT_MAX_ITERATIONS=str(runtime.max_iterations), TZ="UTC",
                   PYTHONPATH=str(hermes))
        launch = "import runpy,sys; p=sys.argv[1]; sys.argv=sys.argv[1:]; runpy.run_path(p,run_name='__main__')"
        with (folder / "worker.log").open("w", encoding="utf-8") as log:
            process = subprocess.run([str(python), "-c", launch, str(worker), str(sample_path), str(folder)],
                                     cwd=hermes, env=env, stdout=log, stderr=subprocess.STDOUT)
        return question_id, process.returncode

    failures = 0
    with ThreadPoolExecutor(max_workers=args.max_concurrency) as executor:
        futures = [executor.submit(run, question_id) for question_id in args.sample_id]
        for future in as_completed(futures):
            question_id, code = future.result()
            failures += code != 0
            print(json.dumps({"question_id": question_id, "completed": code == 0}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
