"""Prepare paired LongMemEval answers for the upstream judge and human review.

The upstream evaluator consumes question_id/hypothesis JSONL and a reference
file with question_id, question_type, question and answer. This module never
generates grades; human annotations and judge results are independent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def index_rows(rows: list[dict]) -> dict[str, dict]:
    indexed = {}
    for row in rows:
        question_id = row["question_id"]
        if question_id in indexed:
            raise ValueError(f"Duplicate question ID: {question_id}")
        indexed[question_id] = row
    return indexed


def prepare(navi_rows: list[dict], hermes_rows: list[dict]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    navi = index_rows(navi_rows)
    hermes = index_rows(hermes_rows)
    if navi.keys() != hermes.keys():
        raise ValueError("Navi and Hermes must contain identical question IDs")
    references, navi_answers, hermes_answers, reviews = [], [], [], []
    for question_id in sorted(navi):
        left, right = navi[question_id], hermes[question_id]
        for field in ("question_type", "question", "reference_answer"):
            if left[field] != right[field]:
                raise ValueError(f"Inconsistent {field} for {question_id}")
        references.append({"question_id": question_id, "question_type": left["question_type"],
                           "question": left["question"], "answer": left["reference_answer"]})
        for result, output in ((left, navi_answers), (right, hermes_answers)):
            if not isinstance(result.get("hypothesis"), str):
                raise ValueError(f"Missing hypothesis for {question_id}")
            output.append({"question_id": question_id, "hypothesis": result["hypothesis"]})
        reviews.append({"question_id": question_id, "question_type": left["question_type"],
                        "navi_runtime_status": left.get("runtime_status"),
                        "hermes_completed": right.get("completed"),
                        "reference_ambiguity": None, "evidence_notes": None,
                        "navi_evidence_supported": None, "hermes_evidence_supported": None,
                        "reviewer": None})
    return references, navi_answers, hermes_answers, reviews


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--navi", type=Path, required=True, help="Navi results JSONL")
    parser.add_argument("--hermes-dir", type=Path, required=True, help="Directory containing per-sample result.json files")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    navi = [json.loads(line) for line in args.navi.read_text(encoding="utf-8").splitlines() if line.strip()]
    hermes = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.hermes_dir.glob("*/result.json"))]
    references, navi_answers, hermes_answers, reviews = prepare(navi, hermes)
    if not references:
        raise ValueError("No paired results found")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "references.json").write_text(json.dumps(references, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, rows in (("navi.jsonl", navi_answers), ("hermes.jsonl", hermes_answers), ("review.jsonl", reviews)):
        (args.output_dir / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
