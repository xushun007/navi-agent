from unittest.mock import patch

from navi_agent.app import ApplicationService
from navi_agent.runtime import (
    AgentRuntime,
    DenyAllApprovalProvider,
    InMemorySessionStore,
    ModelResponse,
    ModelUsage,
)
from navi_agent.telemetry import InMemoryTraceStore

from evals.inspect.adapter import NaviInspectRunner, build_navi_inspect_runner
from evals.inspect.general_qa import load_general_qa_samples, navi_general_qa


class FakeTransport:
    def generate(self, request):
        return ModelResponse(
            content="Jóhanna Sigurðardóttir",
            provider="fake",
            model="fake-model",
            usage=ModelUsage(input_tokens=20, output_tokens=5, cost_usd=0.001),
        )


def build_fake_runner() -> NaviInspectRunner:
    trace_store = InMemoryTraceStore()
    return NaviInspectRunner(
        app=ApplicationService(
            AgentRuntime(
                transport=FakeTransport(),
                session_store=InMemorySessionStore(),
                trace_store=trace_store,
                model="fake-model",
            )
        ),
    )


def test_loads_ten_diverse_simpleqa_samples() -> None:
    samples = load_general_qa_samples()

    assert len(samples) == 10
    assert samples[0].id == "simpleqa-8"
    assert samples[0].target == "Jóhanna Sigurðardóttir"
    assert len({sample.metadata["topic"] for sample in samples}) >= 8


def test_runs_native_navi_runtime_and_exposes_trace_metadata() -> None:
    result = build_fake_runner().run(
        "Who was the former Icelandic prime minister?",
        suite="general-qa",
        sample_id="sample-1",
    )

    assert result.status == "success"
    assert result.completion == "Jóhanna Sigurðardóttir"
    assert result.trace_id
    assert result.iterations == 1
    assert result.input_tokens == 20
    assert result.output_tokens == 5
    assert result.cost_usd == 0.001


def test_builds_inspect_task_with_runtime_and_answer_scorers() -> None:
    task = navi_general_qa(runner=build_fake_runner())

    assert len(task.dataset) == 10
    assert len(task.scorer) == 2
    assert task.metadata["agent"] == "navi-agent"


def test_builds_runner_from_production_application() -> None:
    app = ApplicationService(
        AgentRuntime(
            transport=FakeTransport(),
            session_store=InMemorySessionStore(),
        )
    )

    with patch("evals.inspect.adapter.build_application", return_value=app) as build_app:
        runner = build_navi_inspect_runner(disabled_toolsets=["core"])

    assert isinstance(runner, NaviInspectRunner)
    build_app.assert_called_once()
    assert isinstance(
        build_app.call_args.kwargs["approval_provider"],
        DenyAllApprovalProvider,
    )
    assert build_app.call_args.kwargs["disabled_toolsets"] == ["core"]
