from __future__ import annotations

import json
from pathlib import Path

from inspect_ai.dataset import Sample


DATASET_PATH = Path(__file__).with_name("data") / "bfcl.jsonl"


def load_bfcl_samples(path: Path = DATASET_PATH) -> list[Sample]:
    return [
        Sample(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
