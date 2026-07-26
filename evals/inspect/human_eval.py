from __future__ import annotations

import json
import os
import re
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from evals.inspect.adapter import (
    NaviInspectRunner,
    build_navi_inspect_runner,
    navi_agent_solver,
    navi_runtime_success,
)


DATASET_PATH = Path(__file__).with_name("data") / "human_eval.jsonl"
SANDBOX_DOCKERFILE = Path(__file__).with_name("Dockerfile")
_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)


def load_human_eval_samples(path: Path = DATASET_PATH) -> list[Sample]:
    return [
        Sample(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def extract_python_code(completion: str) -> str:
    fenced_blocks = _CODE_FENCE.findall(completion)
    if fenced_blocks:
        return max(fenced_blocks, key=len).strip()
    return completion.strip()


def resolve_human_eval_sandbox() -> str | tuple[str, str]:
    sandbox_name = os.getenv("NAVI_EVAL_SANDBOX", "docker").strip().lower()
    if sandbox_name == "local":
        return "local"
    if sandbox_name == "docker":
        return ("docker", str(SANDBOX_DOCKERFILE))
    raise ValueError("NAVI_EVAL_SANDBOX must be 'docker' or 'local'")


@scorer(metrics=[accuracy()])
def human_eval_functional_correctness():
    async def score(state: TaskState, target: Target):
        source = extract_python_code(state.output.completion)
        if not source:
            return Score(value="I", explanation="The agent returned no Python code.")

        entry_point = str(state.metadata["entry_point"])
        tests = str(state.metadata["test"])
        program = f"{source.rstrip()}\n{tests.rstrip()}\ncheck({entry_point})\n"
        try:
            result = await sandbox().exec(
                ["python", "-I", "-c", program],
                timeout=10,
                timeout_retry=False,
            )
        except TimeoutError:
            return Score(value="I", explanation="Generated code timed out after 10s.")

        if result.returncode == 0:
            return Score(value="C", explanation="All official HumanEval tests passed.")
        error = (result.stderr or result.stdout or "Python exited with an error.")[-2000:]
        return Score(value="I", explanation=error)

    return score


@task
def navi_human_eval(runner: NaviInspectRunner | None = None) -> Task:
    return Task(
        dataset=load_human_eval_samples(),
        solver=navi_agent_solver(
            suite="human-eval",
            runner=runner or build_navi_inspect_runner(disabled_toolsets=["core"]),
        ),
        scorer=[
            human_eval_functional_correctness(),
            navi_runtime_success(),
        ],
        sandbox=resolve_human_eval_sandbox(),
        metadata={
            "agent": "navi-agent",
            "dataset": "openai/human-eval",
            "sample_count": 10,
        },
    )
