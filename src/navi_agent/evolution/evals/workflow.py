from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from navi_agent.paths import get_eval_seed_path
from navi_agent.paths import get_ifeval_drafts_path
from navi_agent.paths import get_ifeval_reports_dir

from .ifeval import IfevalEvaluator
from .ifeval import IfevalRunRecord
from .ifeval import IfevalRunStore
from .ifeval import IfevalRunWriter
from .seed import EvalSeed
from .seed import EvalSeedStore


@dataclass(frozen=True, slots=True)
class IfevalReviewResult:
    draft_count: int
    draft: EvalSeed | None
    promoted: bool
    skipped: bool
    message: str


@dataclass(frozen=True, slots=True)
class IfevalRunSummary:
    count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    report_path: Path | None
    skipped: bool
    message: str


@dataclass(frozen=True, slots=True)
class IfevalStatusSummary:
    latest_report: IfevalRunRecord | None


@dataclass(frozen=True, slots=True)
class IfevalWorkflowResult:
    review: IfevalReviewResult
    run: IfevalRunSummary
    status: IfevalStatusSummary


class IfevalWorkflowService:
    def __init__(
        self,
        *,
        draft_store: EvalSeedStore | None = None,
        seed_store: EvalSeedStore | None = None,
        report_root: Path | None = None,
        run_seed: Callable[[EvalSeed], tuple[str, str]] | None = None,
        evaluator: IfevalEvaluator | None = None,
    ) -> None:
        self._draft_store = draft_store or EvalSeedStore(get_ifeval_drafts_path())
        self._seed_store = seed_store or EvalSeedStore(get_eval_seed_path())
        self._report_root = report_root or get_ifeval_reports_dir()
        self._run_seed = run_seed
        self._evaluator = evaluator or IfevalEvaluator()

    def review_latest_draft(
        self,
        *,
        confirm_latest_draft: Callable[[EvalSeed], bool] | None = None,
    ) -> IfevalReviewResult:
        drafts = self._draft_store.list_recent(limit=None)
        if not drafts:
            return IfevalReviewResult(
                draft_count=0,
                draft=None,
                promoted=False,
                skipped=True,
                message="no ifeval drafts found",
            )

        draft = drafts[-1]
        if confirm_latest_draft is None:
            return IfevalReviewResult(
                draft_count=len(drafts),
                draft=draft,
                promoted=False,
                skipped=True,
                message="draft review skipped",
            )

        if not confirm_latest_draft(draft):
            return IfevalReviewResult(
                draft_count=len(drafts),
                draft=draft,
                promoted=False,
                skipped=True,
                message="draft review rejected",
            )

        self._seed_store.append(draft)
        removed = self._draft_store.remove_by_key(draft.key)
        if removed is None:
            return IfevalReviewResult(
                draft_count=len(drafts),
                draft=draft,
                promoted=False,
                skipped=False,
                message=f"draft not found after confirmation: {draft.key}",
            )
        return IfevalReviewResult(
            draft_count=len(drafts),
            draft=draft,
            promoted=True,
            skipped=False,
            message=f"promoted draft {draft.key}",
        )

    def run_evaluation(self) -> IfevalRunSummary:
        seeds = self._seed_store.list_recent(limit=None)
        if not seeds:
            return IfevalRunSummary(
                count=0,
                passed_count=0,
                failed_count=0,
                pass_rate=0.0,
                report_path=None,
                skipped=True,
                message="no ifeval seeds found",
            )
        results = []
        for seed in seeds:
            runtime_session_id, runtime_output = self._run_seed_for(seed)
            result = self._evaluator.evaluate(
                key=seed.key,
                session_id=runtime_session_id,
                prompt=seed.prompt,
                output=runtime_output,
                instruction_id_list=seed.instruction_id_list,
                kwargs_list=seed.kwargs,
            )
            results.append(result)
        report_path = IfevalRunWriter(self._report_root).write_run_report(
            seed_store=self._seed_store,
            results=results,
        )
        passed_count = sum(1 for result in results if result.overall_pass)
        failed_count = len(results) - passed_count
        pass_rate = round(passed_count / len(results), 3) if results else 0.0
        return IfevalRunSummary(
            count=len(results),
            passed_count=passed_count,
            failed_count=failed_count,
            pass_rate=pass_rate,
            report_path=report_path,
            skipped=False,
            message="ifeval run completed",
        )

    def status(self) -> IfevalStatusSummary:
        latest = IfevalRunStore(self._report_root).get_latest()
        return IfevalStatusSummary(latest_report=latest)

    def run(
        self,
        *,
        confirm_latest_draft: Callable[[EvalSeed], bool] | None = None,
    ) -> IfevalWorkflowResult:
        review = self.review_latest_draft(confirm_latest_draft=confirm_latest_draft)
        run = self.run_evaluation()
        status = self.status()
        return IfevalWorkflowResult(review=review, run=run, status=status)

    def _run_seed_for(self, seed: EvalSeed) -> tuple[str, str]:
        if self._run_seed is None:
            raise RuntimeError("ifeval workflow run_seed callback is required")
        return self._run_seed(seed)
