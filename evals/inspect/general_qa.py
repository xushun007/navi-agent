from __future__ import annotations

import asyncio
import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant
from inspect_ai.scorer import Score, Target, accuracy, model_graded_qa, scorer
from inspect_ai.solver import TaskState, solver

from evals.inspect.adapter import NaviInspectRunner, build_navi_inspect_runner


DATASET_PATH = Path(__file__).with_name("data") / "general_qa.jsonl"


def load_general_qa_samples(path: Path = DATASET_PATH) -> list[Sample]:
    return [
        Sample(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@solver
def navi_agent_solver(runner: NaviInspectRunner):
    async def solve(state: TaskState, generate):
        result = await asyncio.to_thread(
            runner.run,
            state.user_prompt.text,
            sample_id=str(state.sample_id),
        )
        state.messages.append(ChatMessageAssistant(content=result.completion))
        state.output.completion = result.completion
        state.metadata["navi"] = result.metadata()
        return state

    return solve


@scorer(metrics=[accuracy()])
def navi_runtime_success():
    async def score(state: TaskState, target: Target):
        metadata = state.metadata.get("navi") or {}
        passed = metadata.get("status") == "success" and bool(state.output.completion.strip())
        return Score(
            value="C" if passed else "I",
            explanation=(
                f"status={metadata.get('status')} "
                f"trace_id={metadata.get('trace_id')} "
                f"iterations={metadata.get('iterations')}"
            ),
        )

    return score


@task
def navi_general_qa(runner: NaviInspectRunner | None = None) -> Task:
    return Task(
        dataset=load_general_qa_samples(),
        solver=navi_agent_solver(runner or build_navi_inspect_runner()),
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
