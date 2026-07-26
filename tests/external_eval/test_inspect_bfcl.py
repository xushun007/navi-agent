import asyncio
from types import SimpleNamespace

from inspect_ai.scorer import Target

from evals.inspect.bfcl import (
    BFCLInspectRunner,
    bfcl_tool_call_correctness,
    load_bfcl_samples,
    match_tool_calls,
    navi_bfcl,
)
from navi_agent.runtime import ModelResponse, ModelUsage, ToolCall


def test_loads_balanced_curated_bfcl_samples() -> None:
    samples = load_bfcl_samples()

    assert len(samples) == 10
    assert {sample.metadata["category"] for sample in samples} == {
        "simple",
        "multiple",
        "parallel",
        "irrelevance",
    }
    assert sum(sample.metadata["category"] == "simple" for sample in samples) == 3
    assert sum(sample.metadata["category"] == "multiple" for sample in samples) == 3
    assert sum(sample.metadata["category"] == "parallel" for sample in samples) == 2
    assert sum(sample.metadata["category"] == "irrelevance" for sample in samples) == 2


class FakeTransport:
    def __init__(self) -> None:
        self.responses = [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="calculate_triangle_area",
                        arguments={"base": 10, "height": 5},
                    )
                ],
                usage=ModelUsage(input_tokens=20, output_tokens=5),
            ),
            ModelResponse(
                content="The area is 25 square units.",
                usage=ModelUsage(input_tokens=30, output_tokens=8),
            ),
        ]

    def generate(self, request):
        return self.responses.pop(0)


def test_runs_real_runtime_with_sample_specific_tools() -> None:
    sample = load_bfcl_samples()[0]
    result = BFCLInspectRunner(
        transport=FakeTransport(),
        model="fake-model",
    ).run(
        sample.input,
        sample_id=str(sample.id),
        functions=sample.metadata["functions"],
    )

    assert result.status == "success"
    assert result.iterations == 2
    assert result.tool_calls == (
        {
            "name": "calculate_triangle_area",
            "arguments": {"base": 10, "height": 5},
            "status": "success",
        },
    )
    assert result.input_tokens == 50
    assert result.output_tokens == 13


def test_matches_parallel_calls_without_requiring_order() -> None:
    actual = [
        {
            "name": "calculate_em_force",
            "arguments": {"b_field": 5, "area": 2, "d_time": 10},
            "status": "success",
        },
        {
            "name": "calculate_em_force",
            "arguments": {"b_field": 5, "area": 2, "d_time": 4},
            "status": "success",
        },
    ]
    expected = [
        {"calculate_em_force": {"b_field": [5], "area": [2], "d_time": [4]}},
        {"calculate_em_force": {"b_field": [5], "area": [2], "d_time": [10]}},
    ]

    passed, explanation = match_tool_calls(actual, expected)

    assert passed is True
    assert explanation == "matched 2 expected tool call(s)"


def test_matches_optional_and_nested_arguments() -> None:
    actual = [
        {
            "name": "calculate_average",
            "arguments": {
                "gradeDict": {
                    "math": 90,
                    "science": 75,
                    "history": 82,
                    "music": 89,
                }
            },
            "status": "success",
        }
    ]
    expected = [
        {
            "calculate_average": {
                "gradeDict": [
                    {
                        "math": [90],
                        "science": [75],
                        "history": [82],
                        "music": [89],
                    }
                ]
            }
        }
    ]

    assert match_tool_calls(actual, expected)[0] is True


def test_scores_irrelevance_when_no_tool_is_called() -> None:
    state = SimpleNamespace(
        metadata={
            "navi": {"tool_calls": []},
            "expected_calls": [],
        }
    )

    score = asyncio.run(bfcl_tool_call_correctness()(state, Target("")))

    assert score.value == "C"


def test_rejects_failed_or_extra_tool_calls() -> None:
    failed = [
        {
            "name": "calculate_triangle_area",
            "arguments": {"base": 10, "height": 5},
            "status": "error",
        }
    ]

    assert match_tool_calls(failed, [])[0] is False
    assert match_tool_calls(
        [
            {
                "name": "determine_body_mass_index",
                "arguments": {"weight": 10, "height": 5},
                "status": "success",
            }
        ],
        [],
    )[0] is False


def test_builds_bfcl_task_with_trace_scorers() -> None:
    task = navi_bfcl(
        runner=BFCLInspectRunner(
            transport=FakeTransport(),
            model="fake-model",
        )
    )

    assert len(task.dataset) == 10
    assert len(task.scorer) == 2
    assert task.metadata["dataset"] == "BFCL v4 curated"
