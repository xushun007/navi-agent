from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_USE_SEED_PATH = REPO_ROOT / "data" / "eval" / "tool_use_seed.jsonl"


@dataclass(frozen=True)
class NaviToolUseCase:
    id: str
    level: str
    prompt: str
    required_tools: list[str]
    forbidden_tools: list[str]
    expected_args: dict[str, dict[str, Any]]


def load_tool_use_cases(path: Path = TOOL_USE_SEED_PATH) -> list[NaviToolUseCase]:
    cases: list[NaviToolUseCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        cases.append(
            NaviToolUseCase(
                id=str(payload["id"]),
                level=str(payload["level"]),
                prompt=str(payload["prompt"]),
                required_tools=list(payload.get("required_tools") or []),
                forbidden_tools=list(payload.get("forbidden_tools") or []),
                expected_args=dict(payload.get("expected_args") or {}),
            )
        )
    return cases


def build_navi_eval_command(case_id: str) -> list[str]:
    return [
        "uv",
        "run",
        "navi-agent",
        "--workflow-kind",
        "tool_use_eval",
        "--workflow-phase",
        "run",
        "--workflow-case-id",
        case_id,
    ]


def run_navi_tool_use_case(case_id: str) -> str:
    result = subprocess.run(
        build_navi_eval_command(case_id),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    if result.returncode != 0:
        raise RuntimeError(output or f"navi-agent exited with {result.returncode}")
    return output


def parse_passed(output: str, case_id: str) -> bool:
    return f"{case_id} [pass]" in output and "tool_use_eval_pass_rate: 1.0" in output


def inspect_task():
    try:
        from inspect_ai import Task, task
        from inspect_ai.dataset import Sample
        from inspect_ai.scorer import Score, Target, accuracy, scorer
        from inspect_ai.solver import TaskState, solver
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "inspect_ai is not installed. Install it with `uv add --dev inspect-ai` "
            "or run this adapter with an environment that provides Inspect."
        ) from exc

    @solver
    def navi_solver():
        async def solve(state: TaskState, generate):
            output = run_navi_tool_use_case(str(state.metadata["case_id"]))
            state.output.completion = output
            return state

        return solve

    @scorer(metrics=[accuracy()])
    def navi_scorer():
        async def score(state: TaskState, target: Target):
            case_id = str(state.metadata["case_id"])
            passed = parse_passed(state.output.completion, case_id)
            return Score(value="C" if passed else "I", explanation=state.output.completion)

        return score

    @task
    def navi_tool_use():
        samples = [
            Sample(
                id=case.id,
                input=case.prompt,
                target="pass",
                metadata={
                    "case_id": case.id,
                    "level": case.level,
                    "required_tools": case.required_tools,
                    "forbidden_tools": case.forbidden_tools,
                    "expected_args": case.expected_args,
                },
            )
            for case in load_tool_use_cases()
        ]
        return Task(dataset=samples, solver=navi_solver(), scorer=navi_scorer())

    return navi_tool_use


try:
    navi_tool_use = inspect_task()
except RuntimeError as _inspect_import_error:
    def navi_tool_use(error: RuntimeError = _inspect_import_error):
        raise error
