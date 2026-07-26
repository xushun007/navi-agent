from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import model_graded_qa

from evals.inspect.adapter import (
    NaviInspectRunner,
    build_navi_inspect_runner,
    navi_agent_solver,
    navi_runtime_success,
)


DATASET_PATH = Path(__file__).with_name("data") / "general_qa.jsonl"


def load_general_qa_samples(path: Path = DATASET_PATH) -> list[Sample]:
    return [
        Sample(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@task
def navi_general_qa(runner: NaviInspectRunner | None = None) -> Task:
    return Task(
        dataset=load_general_qa_samples(),
        solver=navi_agent_solver(
            suite="general-qa",
            runner=runner or build_navi_inspect_runner(disabled_toolsets=["core"]),
        ),
        scorer=[
            model_graded_qa(),
            navi_runtime_success(),
        ],
        metadata={
            "agent": "navi-agent",
            "dataset": "codelion/SimpleQA-Verified",
            "sample_count": 10,
        },
    )
