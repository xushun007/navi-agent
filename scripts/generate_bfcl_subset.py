"""Generate a reproducible Navi-compatible BFCL subset from official JSONL data."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


CATEGORY_FILES = {
    "simple": "BFCL_v4_simple_python.json",
    "multiple": "BFCL_v4_multiple.json",
    "parallel": "BFCL_v4_parallel.json",
    "parallel_multiple": "BFCL_v4_parallel_multiple.json",
    "irrelevance": "BFCL_v4_irrelevance.json",
}
CATEGORY_QUOTAS = {
    "simple": 30,
    "multiple": 25,
    "parallel": 15,
    "parallel_multiple": 15,
    "irrelevance": 15,
}
PREFERRED_IDS = {
    "simple_python_0",
    "simple_python_7",
    "simple_python_13",
    "multiple_9",
    "multiple_35",
    "multiple_46",
    "parallel_1",
    "parallel_16",
    "irrelevance_0",
    "irrelevance_5",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_answers(source_dir: Path, filename: str) -> dict[str, list[dict[str, Any]]]:
    path = source_dir / "possible_answer" / filename
    if not path.exists():
        return {}
    return {item["id"]: item["ground_truth"] for item in read_jsonl(path)}


def convert(
    item: dict[str, Any],
    *,
    category: str,
    answers: dict[str, list[dict[str, Any]]],
    source_commit: str,
) -> dict[str, Any]:
    question = item["question"][0][0]["content"]
    expected_calls = answers.get(item["id"], [])
    name_map = {
        function["name"]: normalize_tool_name(function["name"])
        for function in item["function"]
    }
    functions = [
        {**function, "name": name_map[function["name"]]}
        for function in item["function"]
    ]
    expected_calls = [
        {name_map.get(name, name): arguments for name, arguments in call.items()}
        for call in expected_calls
    ]
    return {
        "id": item["id"],
        "input": question,
        "target": "",
        "metadata": {
            "category": category,
            "source": "BFCL v4",
            "source_commit": source_commit,
            "functions": functions,
            "expected_calls": expected_calls,
        },
    }


def normalize_tool_name(name: str) -> str:
    """Map BFCL names to the portable function-name grammar."""
    normalized = re.sub(r"[^A-Za-z0-9_-]", "__", name)
    return normalized or "bfcl_tool"


def build_subset(source_dir: Path, source_commit: str) -> list[dict[str, Any]]:
    selected_by_category: dict[str, list[dict[str, Any]]] = {}
    for category, filename in CATEGORY_FILES.items():
        rows = read_jsonl(source_dir / filename)
        answers = load_answers(source_dir, filename)
        preferred = [row for row in rows if row["id"] in PREFERRED_IDS]
        remaining = [row for row in rows if row["id"] not in PREFERRED_IDS]
        selected = (preferred + remaining)[: CATEGORY_QUOTAS[category]]
        if len(selected) != CATEGORY_QUOTAS[category]:
            raise ValueError(f"not enough {category} samples")
        selected_by_category[category] = [
            convert(
                row,
                category=category,
                answers=answers,
                source_commit=source_commit,
            )
            for row in selected
        ]

    # Interleave categories so a small --limit run remains representative.
    subset: list[dict[str, Any]] = []
    for index in range(max(map(len, selected_by_category.values()))):
        for category in CATEGORY_FILES:
            rows = selected_by_category[category]
            if index < len(rows):
                subset.append(rows[index])
    return subset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    rows = build_subset(args.source_dir, args.source_commit)
    args.output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(rows)} samples to {args.output}")


if __name__ == "__main__":
    main()
