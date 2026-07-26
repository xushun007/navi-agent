from __future__ import annotations

import asyncio
import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.agent import AgentState, agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, accuracy, model_graded_qa, scorer
from inspect_ai.solver import TaskState, solver

from evals.inspect.adapter import run_navi_agent


DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "eval"
    / "inspect"
    / "general_qa.jsonl"
)


def load_general_qa_samples(path: Path = DATASET_PATH) -> list[Sample]:
    return [
        Sample(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@solver
def navi_agent_solver():
    async def solve(state: TaskState, generate):
        bridge_state = AgentState(messages=list(state.messages))
        async with agent_bridge(bridge_state) as bridge:
            result = await asyncio.to_thread(
                run_navi_agent,
                state.user_prompt.text,
                sample_id=str(state.sample_id),
            )
        state.messages = bridge.state.messages
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
def navi_general_qa() -> Task:
    return Task(
        dataset=load_general_qa_samples(),
        solver=navi_agent_solver(),
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
