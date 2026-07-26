import asyncio
from types import SimpleNamespace

from inspect_ai import Task
from inspect_ai.dataset import Sample

from evals.inspect.adapter import navi_runtime_success
from evals.inspect.swe_bench import (
    SWE_BENCH_DATASET,
    SWE_BENCH_SAMPLE_IDS,
    InspectSandboxBridge,
    SWEBenchInspectRunner,
    navi_swe_bench_verified,
    select_swe_bench_samples,
)
from navi_agent.runtime import ModelResponse, ModelUsage, ToolCall


class FakeSandbox:
    def __init__(self) -> None:
        self.files = {"module.py": "def answer():\n    return 1\n"}
        self.commands: list[tuple[list[str], str | None, int | None]] = []

    async def exec(
        self,
        command,
        *,
        cwd=None,
        timeout=None,
        timeout_retry=True,
        **kwargs,
    ):
        self.commands.append((command, cwd, timeout))
        return SimpleNamespace(returncode=0, stdout="tests passed\n", stderr="")

    async def read_file(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write_file(self, path, content):
        self.files[path] = content


class FakeTransport:
    def __init__(self) -> None:
        self.responses = [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="patch",
                        arguments={
                            "path": "module.py",
                            "old": "return 1",
                            "new": "return 2",
                        },
                    )
                ],
                usage=ModelUsage(input_tokens=20, output_tokens=5),
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-2",
                        name="bash",
                        arguments={"command": "pytest -q"},
                    )
                ],
                usage=ModelUsage(input_tokens=30, output_tokens=8),
            ),
            ModelResponse(
                content="Updated the implementation and tests pass.",
                usage=ModelUsage(input_tokens=40, output_tokens=10),
            ),
        ]

    def generate(self, request):
        return self.responses.pop(0)


def _official_task_with_selected_samples() -> Task:
    return Task(
        dataset=[
            Sample(
                id=sample_id,
                input=f"Fix {sample_id}",
                metadata={"repo": sample_id.split("__", 1)[0]},
                sandbox="local",
            )
            for sample_id in reversed(SWE_BENCH_SAMPLE_IDS)
        ],
        scorer=[navi_runtime_success()],
        sandbox="local",
        metadata={"upstream": True},
    )


def test_selects_fifteen_pinned_samples_in_declared_order() -> None:
    samples = list(_official_task_with_selected_samples().dataset)

    selected = select_swe_bench_samples(samples)

    assert len(selected) == 15
    assert [str(sample.id) for sample in selected] == list(SWE_BENCH_SAMPLE_IDS)
    assert len({sample_id.split("__", 1)[0] for sample_id in SWE_BENCH_SAMPLE_IDS}) == 12


def test_rejects_dataset_revision_missing_a_pinned_sample() -> None:
    samples = list(_official_task_with_selected_samples().dataset)[1:]

    try:
        select_swe_bench_samples(samples)
    except ValueError as exc:
        assert "missing from pinned dataset" in str(exc)
    else:
        raise AssertionError("expected a missing pinned sample to fail")


def test_sandbox_bridge_edits_and_executes_inside_inspect_environment() -> None:
    async def run():
        environment = FakeSandbox()
        bridge = InspectSandboxBridge(
            loop=asyncio.get_running_loop(),
            environment=environment,
        )
        registry = bridge.tool_registry()
        runner = SWEBenchInspectRunner(
            transport=FakeTransport(),
            model="fake-model",
        )
        result = await asyncio.to_thread(
            runner.run,
            "Fix the failing answer.",
            sample_id="sample-1",
            sandbox_bridge=bridge,
        )
        return environment, result, registry

    environment, result, registry = asyncio.run(run())

    assert environment.files["module.py"] == "def answer():\n    return 2\n"
    assert environment.commands == [
        (["bash", "--login", "-c", "pytest -q"], None, 210)
    ]
    assert result.status == "success"
    assert result.iterations == 3
    assert result.input_tokens == 90
    assert result.output_tokens == 23
    assert [call["name"] for call in result.tool_calls] == ["patch", "bash"]
    assert {schema["name"] for schema in registry.schemas()} == {
        "bash",
        "patch",
        "read_file",
        "write_file",
    }


def test_builds_task_from_official_inspect_eval_components() -> None:
    task = navi_swe_bench_verified(
        runner=SWEBenchInspectRunner(
            transport=FakeTransport(),
            model="fake-model",
        ),
        official_task_factory=_official_task_with_selected_samples,
    )

    assert len(task.dataset) == 15
    assert [str(sample.id) for sample in task.dataset] == list(SWE_BENCH_SAMPLE_IDS)
    assert task.sandbox.type == "local"
    assert len(task.scorer) == 2
    assert task.metadata["upstream"] is True
    assert task.metadata["dataset"] == SWE_BENCH_DATASET
    assert task.metadata["sample_count"] == 15
