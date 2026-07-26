from __future__ import annotations

from pathlib import Path

from navi_agent.config import ModelSettings, load_config
from navi_agent.paths import get_navi_home


SUPPORTED_INSPECT_SUITES = (
    "general-qa",
    "human-eval",
    "bfcl",
    "agentbench-os",
    "swe-bench-verified",
)


def run_inspect_eval(
    suite: str,
    *,
    limit: int | None = None,
    sample_ids: list[str] | None = None,
    log_dir: Path | None = None,
) -> int:
    from inspect_ai import eval as inspect_eval
    from inspect_ai.model import get_model

    from evals.inspect.general_qa import navi_general_qa
    from evals.inspect.human_eval import navi_human_eval
    from evals.inspect.bfcl import navi_bfcl
    from evals.inspect.agent_bench_os import navi_agent_bench_os
    from evals.inspect.swe_bench import navi_swe_bench_verified

    tasks = {
        "general-qa": navi_general_qa,
        "human-eval": navi_human_eval,
        "bfcl": navi_bfcl,
        "agentbench-os": navi_agent_bench_os,
        "swe-bench-verified": navi_swe_bench_verified,
    }
    task_factory = tasks.get(suite)
    if task_factory is None:
        raise ValueError(f"Unknown evaluation suite: {suite}")

    settings = ModelSettings.from_sources(load_config())
    if not settings.api_key:
        raise ValueError("Navi model API key is required to run evaluations")

    model_name = settings.model if "/" in settings.model else f"openai/{settings.model}"
    grader = get_model(
        model_name,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )
    resolved_log_dir = log_dir or get_navi_home() / "evals" / "inspect"
    logs = inspect_eval(
        task_factory(),
        model=grader,
        model_roles={"grader": grader},
        display="plain",
        log_dir=str(resolved_log_dir),
        limit=limit,
        sample_id=sample_ids or None,
        max_samples=1,
    )

    for log in logs:
        print(f"eval_status: {log.status}")
        print(f"eval_log: {log.location}")
    return 0 if logs and all(log.status == "success" for log in logs) else 1
