import asyncio
from pathlib import Path
from types import SimpleNamespace

from inspect_ai.scorer import Target

from evals.inspect.agent_bench_os import (
    AgentBenchOSRunner,
    agent_bench_os_task_success,
    evaluate_workspace,
    load_agent_bench_os_samples,
    navi_agent_bench_os,
    prepare_workspace,
)
from navi_agent.runtime import ModelResponse, ModelUsage, ToolCall


def test_loads_ten_public_agent_bench_os_dev_samples() -> None:
    samples = load_agent_bench_os_samples()

    assert len(samples) == 10
    assert {sample.metadata["source_id"] for sample in samples} == {
        3,
        6,
        7,
        9,
        10,
        11,
        12,
        21,
        24,
        25,
    }
    assert {sample.metadata["category"] for sample in samples} == {
        "file_query",
        "shell_query",
        "state_change",
    }


class FakeTransport:
    def __init__(self) -> None:
        self.responses = [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="bash",
                        arguments={
                            "command": (
                                "find home -maxdepth 1 -type f "
                                "-name '.*' | wc -l"
                            )
                        },
                    )
                ],
                usage=ModelUsage(input_tokens=20, output_tokens=5),
            ),
            ModelResponse(
                content="6",
                usage=ModelUsage(input_tokens=30, output_tokens=2),
            ),
        ]

    def generate(self, request):
        return self.responses.pop(0)


def test_prepares_and_checks_workspace(tmp_path: Path) -> None:
    prepare_workspace(
        tmp_path,
        {
            "directories": ["home/nested"],
            "files": {"home/test": "#!/bin/sh\necho ok\n", "home/old": "old"},
            "modes": {"home/test": "755"},
            "old_files": ["home/old"],
        },
    )

    assert (tmp_path / "home/nested").is_dir()
    assert (tmp_path / "home/test").stat().st_mode & 0o111
    assert (tmp_path / "home/old").stat().st_mtime < (tmp_path / "home/test").stat().st_mtime
    assert evaluate_workspace(
        tmp_path,
        [{"command": "./home/test", "stdout": "ok"}],
    ) == (True, "passed 1 workspace check(s)")
    assert evaluate_workspace(
        tmp_path,
        [{"command": "printf 3.000001", "numeric_stdout": 3, "tolerance": 1e-5}],
    ) == (True, "passed 1 workspace check(s)")


def test_runs_real_navi_bash_tool_in_isolated_workspace() -> None:
    sample = next(
        sample
        for sample in load_agent_bench_os_samples()
        if sample.id == "agentbench-os-06"
    )
    result = AgentBenchOSRunner(
        transport=FakeTransport(),
        model="fake-model",
    ).run(
        sample.input,
        sample_id=str(sample.id),
        setup=sample.metadata["setup"],
        checks=sample.metadata["checks"],
    )

    assert result.navi.status == "success"
    assert result.navi.completion == "6"
    assert result.navi.tool_calls[0]["name"] == "bash"
    assert result.navi.tool_calls[0]["status"] == "success"
    assert result.environment_passed is True


def test_scores_answer_and_environment_together() -> None:
    state = SimpleNamespace(
        output=SimpleNamespace(completion="Awesome-AgentBench"),
        metadata={
            "navi": {
                "environment_passed": True,
                "environment_explanation": "passed 2 workspace check(s)",
            }
        },
    )

    score = asyncio.run(
        agent_bench_os_task_success()(state, Target("Awesome-AgentBench"))
    )

    assert score.value == "C"


def test_rejects_correct_answer_when_workspace_check_failed() -> None:
    state = SimpleNamespace(
        output=SimpleNamespace(completion="Awesome-AgentBench"),
        metadata={
            "navi": {
                "environment_passed": False,
                "environment_explanation": "not executable",
            }
        },
    )

    score = asyncio.run(
        agent_bench_os_task_success()(state, Target("Awesome-AgentBench"))
    )

    assert score.value == "I"


def test_builds_agent_bench_os_task() -> None:
    task = navi_agent_bench_os(
        runner=AgentBenchOSRunner(
            transport=FakeTransport(),
            model="fake-model",
        )
    )

    assert len(task.dataset) == 10
    assert len(task.scorer) == 2
    assert task.metadata["dataset"] == "AgentBench OS dev curated"
