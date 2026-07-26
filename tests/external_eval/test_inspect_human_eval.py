import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from inspect_ai.scorer import Target
from inspect_ai.util import ExecResult

from evals.inspect.human_eval import (
    extract_python_code,
    human_eval_functional_correctness,
    load_human_eval_samples,
    navi_human_eval,
)
from tests.external_eval.test_inspect_general_qa import build_fake_runner


def test_loads_ten_diverse_human_eval_samples() -> None:
    samples = load_human_eval_samples()

    assert len(samples) == 10
    assert samples[0].id == "HumanEval/0"
    assert samples[-1].id == "HumanEval/160"
    assert len({sample.metadata["entry_point"] for sample in samples}) == 10


def test_extracts_python_code_from_markdown_fence() -> None:
    completion = "Here is the solution:\n```python\ndef answer():\n    return 42\n```"

    assert extract_python_code(completion) == "def answer():\n    return 42"


def test_preserves_unfenced_python_code() -> None:
    completion = "def answer():\n    return 42"

    assert extract_python_code(completion) == completion


def test_builds_human_eval_task_with_docker_sandbox() -> None:
    task = navi_human_eval(runner=build_fake_runner())

    assert len(task.dataset) == 10
    assert len(task.scorer) == 2
    assert task.sandbox.type == "docker"
    assert task.metadata["dataset"] == "openai/human-eval"


def test_scores_generated_code_with_official_tests() -> None:
    state = SimpleNamespace(
        output=SimpleNamespace(completion="def answer():\n    return 42"),
        metadata={
            "entry_point": "answer",
            "test": "def check(candidate):\n    assert candidate() == 42",
        },
    )
    environment = SimpleNamespace(
        exec=AsyncMock(return_value=ExecResult(True, 0, "", "")),
    )

    with patch("evals.inspect.human_eval.sandbox", return_value=environment):
        score = asyncio.run(human_eval_functional_correctness()(state, Target("answer")))

    assert score.value == "C"
    command = environment.exec.call_args.args[0]
    assert command[:3] == ["python", "-I", "-c"]
    assert "check(answer)" in command[3]
