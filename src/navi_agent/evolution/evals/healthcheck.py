from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from navi_agent.app import AppRequest, ApplicationService
from navi_agent.evolution import EvaluationResult, EvolutionCandidate, SimpleEvaluator, EvalCase
from navi_agent.evolution import ReviewLoopService
from navi_agent.evolution import EvolutionReportWriter
from navi_agent.paths import get_evolution_reports_dir
from navi_agent.runtime import RuntimeResult
from navi_agent.telemetry import RuntimeTrace


@dataclass(frozen=True, slots=True)
class HealthcheckTask:
    name: str
    description: str
    prompt: str


@dataclass(frozen=True, slots=True)
class HealthcheckWorkflow:
    name: str
    description: str
    steps: list[str]


@dataclass(frozen=True, slots=True)
class HealthcheckStepResult:
    task_name: str
    runtime_result: RuntimeResult
    trace: RuntimeTrace | None = None

    @property
    def trace_id(self) -> str | None:
        if self.trace is None:
            return None
        return self.trace.trace_id

    @property
    def trace_status(self) -> str | None:
        if self.trace is None:
            return None
        return self.trace.status


@dataclass(frozen=True, slots=True)
class HealthcheckWorkflowResult:
    workflow: HealthcheckWorkflow
    session_id: str
    user_id: str
    system_prompt: str | None
    steps: list[HealthcheckStepResult]


@dataclass(frozen=True, slots=True)
class HealthcheckStepComparison:
    task_name: str
    source_step: HealthcheckStepResult
    replay_step: HealthcheckStepResult
    source_evaluation: EvaluationResult | None
    replay_evaluation: EvaluationResult | None
    score_delta: float


@dataclass(frozen=True, slots=True)
class HealthcheckWorkflowComparison:
    workflow_name: str
    source_session_id: str
    replay_session_id: str
    step_comparisons: list[HealthcheckStepComparison]
    source_average_score: float
    replay_average_score: float
    score_delta: float
    eval_case: EvalCase
    candidate: EvolutionCandidate | None


@dataclass(frozen=True, slots=True)
class HealthcheckComparisonReport:
    comparison: HealthcheckWorkflowComparison
    report_dir: Path
    eval_case_saved: bool


HEALTHCHECK_TASKS: dict[str, HealthcheckTask] = {
    "readme-summary": HealthcheckTask(
        name="readme-summary",
        description="Read the project README and summarize the current product goal.",
        prompt="阅读 README.md，简要总结这个项目的目标、当前范围和后续方向。",
    ),
    "runtime-trace-check": HealthcheckTask(
        name="runtime-trace-check",
        description="Inspect runtime and telemetry code, then summarize the trace flow.",
        prompt="检查 src/navi_agent/runtime 和 src/navi_agent/telemetry，说明一次运行的 trace 是如何被记录和导出的。",
    ),
    "config-check": HealthcheckTask(
        name="config-check",
        description="Inspect config.example.yaml and explain the minimum required configuration.",
        prompt="读取 config.example.yaml，说明运行这个 agent 最少需要配置哪些字段。",
    ),
    "workspace-search": HealthcheckTask(
        name="workspace-search",
        description="Use file search tools to locate the main CLI and runtime entrypoints.",
        prompt="定位这个项目的 CLI 入口、应用入口和 runtime 入口，并简要说明它们的关系。",
    ),
}

HEALTHCHECK_WORKFLOWS: dict[str, HealthcheckWorkflow] = {
    "agent-healthcheck": HealthcheckWorkflow(
        name="agent-healthcheck",
        description="Run the config, entrypoint, and trace-flow health checks.",
        steps=[
            "config-check",
            "workspace-search",
            "runtime-trace-check",
        ],
    ),
    "product-orientation": HealthcheckWorkflow(
        name="product-orientation",
        description="Verify README understanding and project entrypoint discovery.",
        steps=[
            "readme-summary",
            "workspace-search",
        ],
    ),
}


def list_healthcheck_tasks() -> list[HealthcheckTask]:
    return [HEALTHCHECK_TASKS[name] for name in sorted(HEALTHCHECK_TASKS)]


def list_healthcheck_workflows() -> list[HealthcheckWorkflow]:
    return [HEALTHCHECK_WORKFLOWS[name] for name in sorted(HEALTHCHECK_WORKFLOWS)]


def get_healthcheck_task(name: str) -> HealthcheckTask:
    try:
        return HEALTHCHECK_TASKS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown healthcheck task: {name}") from exc


def run_healthcheck_task(
    *,
    app: ApplicationService,
    task_name: str,
    user_id: str,
    session_id: str | None = None,
    system_prompt: str | None = None,
):
    task = get_healthcheck_task(task_name)
    return app.handle(
        AppRequest(
            user_id=user_id,
            session_id=session_id or f"healthcheck-{task.name}-{uuid4().hex[:8]}",
            message=task.prompt,
            system_prompt=system_prompt,
            auto_propose_eval_case=False,
        )
    )


def get_healthcheck_workflow(name: str) -> HealthcheckWorkflow:
    try:
        return HEALTHCHECK_WORKFLOWS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown healthcheck workflow: {name}") from exc


def run_healthcheck_workflow(
    *,
    app: ApplicationService,
    workflow_name: str,
    user_id: str,
    session_id: str | None = None,
    system_prompt: str | None = None,
) -> HealthcheckWorkflowResult:
    workflow = get_healthcheck_workflow(workflow_name)
    workflow_session_id = session_id or f"workflow-{workflow.name}-{uuid4().hex[:8]}"
    steps: list[HealthcheckStepResult] = []

    for task_name in workflow.steps:
        result = run_healthcheck_task(
            app=app,
            task_name=task_name,
            user_id=user_id,
            session_id=workflow_session_id,
            system_prompt=system_prompt,
        )
        latest_trace = app.get_latest_trace(
            session_id=workflow_session_id,
            user_id=user_id,
        )
        steps.append(
            HealthcheckStepResult(
                task_name=task_name,
                runtime_result=result,
                trace=latest_trace,
            )
        )

    return HealthcheckWorkflowResult(
        workflow=workflow,
        session_id=workflow_session_id,
        user_id=user_id,
        system_prompt=system_prompt,
        steps=steps,
    )


def replay_healthcheck_workflow(
    *,
    app: ApplicationService,
    workflow_result: HealthcheckWorkflowResult,
    user_id: str | None = None,
    session_id: str | None = None,
    system_prompt: str | None = None,
) -> HealthcheckWorkflowResult:
    replay_session_id = session_id or f"{workflow_result.session_id}:replay:{uuid4().hex[:8]}"
    return run_healthcheck_workflow(
        app=app,
        workflow_name=workflow_result.workflow.name,
        user_id=user_id or workflow_result.user_id,
        session_id=replay_session_id,
        system_prompt=workflow_result.system_prompt if system_prompt is None else system_prompt,
    )


def compare_healthcheck_workflow_results(
    source: HealthcheckWorkflowResult,
    replay: HealthcheckWorkflowResult,
    *,
    evaluator: SimpleEvaluator | None = None,
) -> HealthcheckWorkflowComparison:
    if source.workflow.name != replay.workflow.name:
        raise ValueError("Cannot compare workflow results from different workflows")
    if len(source.steps) != len(replay.steps):
        raise ValueError("Cannot compare workflow results with different step counts")

    evaluator = evaluator or SimpleEvaluator()
    step_comparisons: list[HealthcheckStepComparison] = []

    for source_step, replay_step in zip(source.steps, replay.steps, strict=True):
        source_evaluation = evaluator.evaluate(source_step.trace) if source_step.trace is not None else None
        replay_evaluation = evaluator.evaluate(replay_step.trace) if replay_step.trace is not None else None
        source_score = source_evaluation.score if source_evaluation is not None else 0.0
        replay_score = replay_evaluation.score if replay_evaluation is not None else 0.0
        step_comparisons.append(
            HealthcheckStepComparison(
                task_name=source_step.task_name,
                source_step=source_step,
                replay_step=replay_step,
                source_evaluation=source_evaluation,
                replay_evaluation=replay_evaluation,
                score_delta=round(replay_score - source_score, 3),
            )
        )

    source_average_score = _average_score(
        comparison.source_evaluation.score
        for comparison in step_comparisons
        if comparison.source_evaluation is not None
    )
    replay_average_score = _average_score(
        comparison.replay_evaluation.score
        for comparison in step_comparisons
        if comparison.replay_evaluation is not None
    )

    score_delta = round(replay_average_score - source_average_score, 3)
    eval_case = _build_eval_case(
        workflow_name=source.workflow.name,
        source_session_id=source.session_id,
        replay_session_id=replay.session_id,
        source_average_score=source_average_score,
        replay_average_score=replay_average_score,
        score_delta=score_delta,
        step_comparisons=step_comparisons,
    )
    candidate = _build_candidate_from_comparison(
        step_comparisons=step_comparisons,
        eval_case=eval_case,
        evaluator=evaluator,
    )

    return HealthcheckWorkflowComparison(
        workflow_name=source.workflow.name,
        source_session_id=source.session_id,
        replay_session_id=replay.session_id,
        step_comparisons=step_comparisons,
        source_average_score=source_average_score,
        replay_average_score=replay_average_score,
        score_delta=score_delta,
        eval_case=eval_case,
        candidate=candidate,
    )


class HealthcheckWorkflowService:
    def __init__(
        self,
        *,
        app: ApplicationService,
        report_root: Path | None = None,
        evaluator: SimpleEvaluator | None = None,
    ) -> None:
        self._app = app
        self._report_root = report_root or get_evolution_reports_dir()
        self._evaluator = evaluator or SimpleEvaluator()

    def run_comparison_workflow(
        self,
        *,
        workflow_name: str,
        user_id: str,
        session_id: str | None = None,
        system_prompt: str | None = None,
        confirm_eval_case: bool = False,
        confirm_eval_case_callback=None,
    ) -> HealthcheckComparisonReport:
        source = run_healthcheck_workflow(
            app=self._app,
            workflow_name=workflow_name,
            user_id=user_id,
            session_id=session_id,
            system_prompt=system_prompt,
        )
        replay = replay_healthcheck_workflow(
            app=self._app,
            workflow_result=source,
            system_prompt=system_prompt,
        )
        return self.finalize_comparison(
            source=source,
            replay=replay,
            confirm_eval_case=confirm_eval_case,
            confirm_eval_case_callback=confirm_eval_case_callback,
        )

    def finalize_comparison(
        self,
        *,
        source: HealthcheckWorkflowResult,
        replay: HealthcheckWorkflowResult,
        confirm_eval_case: bool = False,
        confirm_eval_case_callback=None,
    ) -> HealthcheckComparisonReport:
        comparison = compare_healthcheck_workflow_results(
            source,
            replay,
            evaluator=self._evaluator,
        )
        save_eval_case = True
        if confirm_eval_case and confirm_eval_case_callback is not None:
            save_eval_case = bool(confirm_eval_case_callback(comparison))
        if save_eval_case:
            self._app.add_eval_case(comparison.eval_case)
        if comparison.candidate is not None:
            self._app.add_candidate(comparison.candidate)
        review_summary = ReviewLoopService().summarize(
            candidates=self._app.list_candidates(limit=50),
            eval_cases=self._app.list_eval_cases(limit=50),
        )
        report_dir = EvolutionReportWriter(self._report_root).write_workflow_comparison_report(
            comparison=comparison,
            review_summary=review_summary,
        )
        return HealthcheckComparisonReport(
            comparison=comparison,
            report_dir=report_dir,
            eval_case_saved=save_eval_case,
        )


def _average_score(scores) -> float:
    values = list(scores)
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _build_eval_case(
    *,
    workflow_name: str,
    source_session_id: str,
    replay_session_id: str,
    source_average_score: float,
    replay_average_score: float,
    score_delta: float,
    step_comparisons: list[HealthcheckStepComparison],
) -> EvalCase:
    if score_delta > 0.01:
        status = "improved"
        summary = "Workflow replay improved over the source run"
    elif score_delta < -0.01:
        status = "regressed"
        summary = "Workflow replay regressed compared with the source run"
    else:
        status = "unchanged"
        summary = "Workflow replay produced roughly the same score as the source run"

    return EvalCase(
        workflow_name=workflow_name,
        source_session_id=source_session_id,
        replay_session_id=replay_session_id,
        source_average_score=source_average_score,
        replay_average_score=replay_average_score,
        score_delta=score_delta,
        status=status,
        summary=summary,
        metadata={
            "step_count": len(step_comparisons),
            "steps": [
                {
                    "task_name": comparison.task_name,
                    "source_trace_id": comparison.source_step.trace_id,
                    "replay_trace_id": comparison.replay_step.trace_id,
                    "score_delta": comparison.score_delta,
                }
                for comparison in step_comparisons
            ],
        },
    )


def _build_candidate_from_comparison(
    *,
    step_comparisons: list[HealthcheckStepComparison],
    eval_case: EvalCase,
    evaluator: SimpleEvaluator,
) -> EvolutionCandidate | None:
    worst_step = min(
        step_comparisons,
        key=lambda comparison: (
            comparison.replay_evaluation.score
            if comparison.replay_evaluation is not None
            else 1.0
        ),
        default=None,
    )
    if worst_step is None or worst_step.replay_evaluation is None:
        return None

    candidate = evaluator.build_candidate(worst_step.replay_evaluation)
    if candidate is None:
        return None

    candidate.metadata.update(
        {
            "workflow_name": eval_case.workflow_name,
            "workflow_status": eval_case.status,
            "workflow_score_delta": eval_case.score_delta,
            "source_session_id": eval_case.source_session_id,
            "replay_session_id": eval_case.replay_session_id,
            "task_name": worst_step.task_name,
            "source_trace_id": worst_step.source_step.trace_id,
            "replay_trace_id": worst_step.replay_step.trace_id,
            "step_score_delta": worst_step.score_delta,
        }
    )

    if eval_case.status == "regressed":
        candidate.summary = f"Review healthcheck regression in {worst_step.task_name} ({candidate.target})"
    elif eval_case.status == "unchanged":
        candidate.summary = f"Review stagnant healthcheck step {worst_step.task_name} ({candidate.target})"

    return candidate
