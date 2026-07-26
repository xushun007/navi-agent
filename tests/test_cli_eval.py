from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from navi_agent.cli.eval import run_inspect_eval
from navi_agent.config import ModelSettings


def test_runs_inspect_with_navi_model_configuration() -> None:
    fake_task = object()
    fake_grader = object()
    fake_log = SimpleNamespace(status="success", location="/tmp/eval.eval")

    with patch(
        "navi_agent.cli.eval.ModelSettings.from_sources",
        return_value=ModelSettings(
            model="deepseek-v4-pro",
            api_key="token",
            base_url="https://example.test/v1",
        ),
    ):
        with patch("inspect_ai.model.get_model", return_value=fake_grader) as get_model:
            with patch(
                "evals.inspect.general_qa.navi_general_qa",
                return_value=fake_task,
            ):
                with patch(
                    "inspect_ai.eval",
                    return_value=[fake_log],
                ) as inspect_eval:
                    exit_code = run_inspect_eval(
                        "general-qa",
                        limit=5,
                        sample_ids=["simpleqa-8"],
                        log_dir=Path("/tmp/logs"),
                    )

    assert exit_code == 0
    get_model.assert_called_once_with(
        "openai/deepseek-v4-pro",
        api_key="token",
        base_url="https://example.test/v1",
    )
    assert inspect_eval.call_args.args == (fake_task,)
    assert inspect_eval.call_args.kwargs["model"] is fake_grader
    assert inspect_eval.call_args.kwargs["model_roles"] == {"grader": fake_grader}
    assert inspect_eval.call_args.kwargs["limit"] == 5
    assert inspect_eval.call_args.kwargs["sample_id"] == ["simpleqa-8"]
    assert inspect_eval.call_args.kwargs["max_samples"] == 1


def test_rejects_unknown_inspect_suite() -> None:
    try:
        run_inspect_eval("missing")
    except ValueError as exc:
        assert str(exc) == "Unknown evaluation suite: missing"
    else:
        raise AssertionError("expected unknown suite to fail")
