import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from navi_agent.runtime import Message, ModelRequest, ModelResponse, ModelUsage

from evals.inspect.adapter import InspectBridgeTransport, run_navi_agent
from evals.inspect.general_qa import load_general_qa_samples, navi_general_qa


class FakeTransport:
    def generate(self, request):
        return ModelResponse(
            content="Jóhanna Sigurðardóttir",
            provider="fake",
            model="fake-model",
            usage=ModelUsage(input_tokens=20, output_tokens=5, cost_usd=0.001),
        )


def test_loads_ten_diverse_simpleqa_samples() -> None:
    samples = load_general_qa_samples()

    assert len(samples) == 10
    assert samples[0].id == "simpleqa-8"
    assert samples[0].target == "Jóhanna Sigurðardóttir"
    assert len({sample.metadata["topic"] for sample in samples}) >= 8


def test_runs_native_navi_runtime_and_exposes_trace_metadata() -> None:
    result = run_navi_agent(
        "Who was the former Icelandic prime minister?",
        sample_id="sample-1",
        transport=FakeTransport(),
    )

    assert result.status == "success"
    assert result.completion == "Jóhanna Sigurðardóttir"
    assert result.trace_id
    assert result.iterations == 1
    assert result.input_tokens == 20
    assert result.output_tokens == 5
    assert result.cost_usd == 0.001


def test_maps_openai_bridge_response_to_navi_response() -> None:
    response = SimpleNamespace(
        model="mock-model",
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content="answer",
                    tool_calls=None,
                ),
            )
        ],
    )

    mapped = InspectBridgeTransport._to_model_response(response)

    assert mapped.content == "answer"
    assert mapped.provider == "inspect"
    assert mapped.model == "mock-model"
    assert mapped.usage.input_tokens == 12
    assert mapped.usage.output_tokens == 3


def test_passes_empty_tool_list_to_agent_bridge() -> None:
    response = SimpleNamespace(
        model="mock-model",
        usage=None,
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="answer", tool_calls=None),
            )
        ],
    )
    create = AsyncMock(return_value=response)
    client = AsyncMock()
    client.chat.completions.create = create
    client.__aenter__.return_value = client
    request = ModelRequest(
        messages=[Message(role="user", content="question")],
        tools=[],
    )

    with patch("evals.inspect.adapter.AsyncOpenAI", return_value=client):
        result = asyncio.run(InspectBridgeTransport()._generate(request))

    assert result.content == "answer"
    assert create.await_args.kwargs["tools"] == []


def test_builds_inspect_task_with_runtime_and_answer_scorers() -> None:
    task = navi_general_qa()

    assert len(task.dataset) == 10
    assert len(task.scorer) == 2
    assert task.metadata["agent"] == "navi-agent"
