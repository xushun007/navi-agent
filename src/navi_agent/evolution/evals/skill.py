from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from navi_agent.runtime import RuntimeResult
from navi_agent.telemetry import RuntimeTrace

from ..core.models import EvalCase, EvaluationResult
from ..skills.governance import (
    SkillEvaluationResult,
    SkillGovernanceService,
)
from ..skills.store import FileSkillStore
from .report import EvolutionReportWriter


@dataclass(frozen=True, slots=True)
class SkillEvalCase:
    id: str
    prompt: str
    required_output_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillEvalRun:
    task_name: str
    runtime_result: RuntimeResult
    trace: RuntimeTrace | None = None

    @property
    def trace_id(self) -> str | None:
        return self.trace.trace_id if self.trace is not None else None


@dataclass(frozen=True, slots=True)
class SkillEvalStepComparison:
    task_name: str
    source_step: SkillEvalRun
    replay_step: SkillEvalRun
    source_evaluation: EvaluationResult
    replay_evaluation: EvaluationResult
    score_delta: float


@dataclass(frozen=True, slots=True)
class SkillEvalComparison:
    workflow_name: str
    source_session_id: str
    replay_session_id: str
    step_comparisons: list[SkillEvalStepComparison]
    source_average_score: float
    replay_average_score: float
    score_delta: float
    eval_case: EvalCase
    candidate: None = None


@dataclass(frozen=True, slots=True)
class SkillEvalSummary:
    draft_id: str
    skill_name: str
    comparison: SkillEvalComparison
    evaluation_result: SkillEvaluationResult
    report_path: Path


SkillCaseRunner = Callable[[SkillEvalCase, FileSkillStore, str], SkillEvalRun]


class SkillEvalWorkflowService:
    """Evaluate any admitted skill draft without activating it."""

    def __init__(
        self,
        *,
        skill_store: FileSkillStore,
        governance: SkillGovernanceService,
        runner: SkillCaseRunner,
        report_writer: EvolutionReportWriter,
    ) -> None:
        self._skill_store = skill_store
        self._governance = governance
        self._runner = runner
        self._report_writer = report_writer

    def evaluate(
        self,
        draft_id: str,
        *,
        cases: Sequence[SkillEvalCase],
    ) -> SkillEvalSummary:
        draft = self._governance.get_draft(draft_id)
        if draft is None or draft.status != "candidate":
            raise ValueError(f"skill draft is not admitted for evaluation: {draft_id}")
        draft_skill = self._governance.get_draft_skill(draft_id)
        if draft_skill is None:
            raise ValueError(f"skill draft content is missing: {draft_id}")
        if not cases:
            raise ValueError("skill evaluation requires at least one case")

        with TemporaryDirectory(prefix="navi-skill-eval-") as temporary:
            root = Path(temporary)
            baseline_store = self._copy_store(root / "baseline")
            variant_store = self._copy_store(root / "variant")
            self._replace_skill(variant_store, draft_skill.path.parent)
            comparisons = [
                self._run_case(case, baseline_store=baseline_store, variant_store=variant_store)
                for case in cases
            ]

        comparison = self._build_comparison(
            draft_id=draft_id,
            skill_name=draft.skill_name,
            cases=cases,
            comparisons=comparisons,
        )
        report_path = self._report_writer.write_workflow_comparison_report(
            comparison=comparison
        )
        evaluation_result = SkillEvaluationResult(
            suite="skill_ab",
            passed=(
                comparison.eval_case.metadata["correctness_passed"]
                and comparison.replay_average_score >= comparison.source_average_score
            ),
            baseline_score=comparison.source_average_score,
            draft_score=comparison.replay_average_score,
            reason="isolated baseline/variant skill evaluation",
        )
        return SkillEvalSummary(
            draft_id=draft_id,
            skill_name=draft.skill_name,
            comparison=comparison,
            evaluation_result=evaluation_result,
            report_path=report_path,
        )

    def _copy_store(self, destination: Path) -> FileSkillStore:
        destination.mkdir(parents=True, exist_ok=True)
        for skill in self._skill_store.list():
            shutil.copytree(skill.path.parent, destination / skill.name)
        return FileSkillStore(destination)

    @staticmethod
    def _replace_skill(store: FileSkillStore, source: Path) -> None:
        target = store.root / source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

    def _run_case(
        self,
        case: SkillEvalCase,
        *,
        baseline_store: FileSkillStore,
        variant_store: FileSkillStore,
    ) -> SkillEvalStepComparison:
        baseline = self._runner(case, baseline_store, "baseline")
        variant = self._runner(case, variant_store, "variant")
        baseline_evaluation = _evaluate_run(case, baseline)
        variant_evaluation = _evaluate_run(case, variant)
        return SkillEvalStepComparison(
            task_name=case.id,
            source_step=baseline,
            replay_step=variant,
            source_evaluation=baseline_evaluation,
            replay_evaluation=variant_evaluation,
            score_delta=round(variant_evaluation.score - baseline_evaluation.score, 3),
        )

    @staticmethod
    def _build_comparison(
        *,
        draft_id: str,
        skill_name: str,
        cases: Sequence[SkillEvalCase],
        comparisons: list[SkillEvalStepComparison],
    ) -> SkillEvalComparison:
        baseline_score = _average(item.source_evaluation.score for item in comparisons)
        variant_score = _average(item.replay_evaluation.score for item in comparisons)
        score_delta = round(variant_score - baseline_score, 3)
        correctness = [
            {
                "task_name": item.task_name,
                "correctness_passed": item.replay_evaluation.score == 1.0,
                "missing_terms": item.replay_evaluation.metadata.get("missing_terms", []),
            }
            for item in comparisons
        ]
        workflow_name = f"skill:{skill_name}"
        eval_case = EvalCase(
            workflow_name=workflow_name,
            source_session_id=f"{draft_id}:baseline",
            replay_session_id=f"{draft_id}:variant",
            source_average_score=baseline_score,
            replay_average_score=variant_score,
            score_delta=score_delta,
            status=_comparison_status(score_delta),
            summary="Isolated skill baseline/variant comparison",
            metadata={
                "case_fingerprint": _case_fingerprint(cases),
                "correctness_passed": all(item["correctness_passed"] for item in correctness),
                "draft_id": draft_id,
                "skill_name": skill_name,
                "steps": correctness,
            },
        )
        return SkillEvalComparison(
            workflow_name=workflow_name,
            source_session_id=eval_case.source_session_id,
            replay_session_id=eval_case.replay_session_id,
            step_comparisons=comparisons,
            source_average_score=baseline_score,
            replay_average_score=variant_score,
            score_delta=score_delta,
            eval_case=eval_case,
        )


def _evaluate_run(case: SkillEvalCase, run: SkillEvalRun) -> EvaluationResult:
    output = run.runtime_result.final_response.lower()
    missing = [term for term in case.required_output_terms if term.lower() not in output]
    passed = run.runtime_result.status == "success" and not missing
    return EvaluationResult(
        session_id=run.runtime_result.session_id,
        score=1.0 if passed else 0.0,
        summary="passed" if passed else "failed deterministic skill assertions",
        metadata={
            "missing_terms": missing,
            "failure_attribution": {
                "primary_failure": "none" if passed else "correctness",
                "counts": {} if passed else {"correctness": 1},
            },
        },
    )


def _average(values) -> float:
    scores = list(values)
    return round(sum(scores) / len(scores), 3) if scores else 0.0


def _comparison_status(delta: float) -> str:
    if delta > 0.01:
        return "improved"
    if delta < -0.01:
        return "regressed"
    return "unchanged"


def _case_fingerprint(cases: Sequence[SkillEvalCase]) -> str:
    payload = [
        {
            "id": case.id,
            "prompt": case.prompt,
            "required_output_terms": list(case.required_output_terms),
        }
        for case in cases
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode('utf-8')).hexdigest()}"
