from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from navi_agent.app.bootstrap import build_runtime
from navi_agent.config import ModelSettings, RuntimeSettings, load_config
from navi_agent.evolution import (
    DefaultSkillAdmissionValidator,
    EvolutionReportWriter,
    FileSkillStore,
    SkillDraftProvenance,
    SkillEvalCase,
    SkillEvalRun,
    SkillEvalWorkflowService,
    SkillGovernanceService,
    SkillPromotionGate,
)
from navi_agent.paths import get_evolution_reports_dir, get_skills_dir
from navi_agent.runtime import (
    ApprovalProvider,
    RuntimeMode,
)


def stage_skill_directory(path: Path, *, source_kind: str) -> str:
    if source_kind not in {"human", "external"}:
        raise ValueError("source_kind must be human or external")
    governance = _governance()
    draft = governance.import_draft(
        source=path,
        provenance=SkillDraftProvenance(
            source_kind=source_kind,
            source_uri=str(path.resolve()),
        ),
    )
    admitted = governance.admit(
        draft.draft_id,
        validator=DefaultSkillAdmissionValidator(),
    )
    if admitted.status != "candidate":
        raise ValueError(admitted.decision_reason)
    return admitted.draft_id


def run_skill_evaluation(
    draft_id: str,
    *,
    case_file: Path,
    approval_provider: ApprovalProvider,
    system_prompt: str | None = None,
) -> tuple[Path, bool]:
    config = load_config()
    model_settings = ModelSettings.from_sources(config)
    runtime_settings = RuntimeSettings.from_sources(config)
    governance = _governance()
    cases = load_skill_eval_cases(case_file)

    def run_case(case: SkillEvalCase, skill_store: FileSkillStore, condition: str):
        runtime = build_runtime(
            model_settings=model_settings,
            runtime_settings=runtime_settings,
            approval_provider=approval_provider,
            skill_store=skill_store,
        )
        session_id = f"skill-eval:{draft_id}:{case.id}:{condition}:{uuid4().hex[:8]}"
        result = runtime.run_conversation(
            session_id=session_id,
            user_id="skill-eval",
            user_message=case.prompt,
            system_prompt=system_prompt,
            mode=RuntimeMode.EVAL,
        )
        return SkillEvalRun(
            task_name=case.id,
            runtime_result=result,
            trace=runtime.get_latest_trace(session_id=session_id, user_id="skill-eval"),
        )

    summary = SkillEvalWorkflowService(
        skill_store=FileSkillStore(get_skills_dir()),
        governance=governance,
        runner=run_case,
        report_writer=EvolutionReportWriter(get_evolution_reports_dir() / "skills"),
    ).evaluate(draft_id, cases=cases)
    governance.record_evaluation(
        draft_id,
        evaluation_results=[summary.evaluation_result],
        case_fingerprint=str(summary.comparison.eval_case.metadata["case_fingerprint"]),
        model_config_fingerprint=_model_config_fingerprint(
            model_settings=model_settings,
            runtime_settings=runtime_settings,
            system_prompt=system_prompt,
        ),
        report_path=str(summary.report_path.resolve()),
        source_session_id=summary.comparison.source_session_id,
        replay_session_id=summary.comparison.replay_session_id,
        trace_ids=tuple(
            trace_id
            for step in summary.comparison.step_comparisons
            for trace_id in (step.source_step.trace_id, step.replay_step.trace_id)
            if trace_id
        ),
    )
    return summary.report_path, summary.evaluation_result.passed


def activate_skill_draft(draft_id: str) -> str:
    governance = _governance()
    draft = governance.get_draft(draft_id)
    if draft is None:
        raise ValueError(f"draft not found: {draft_id}")
    if not draft.evaluation_results:
        raise ValueError("skill draft has no recorded evaluation evidence")
    activated = governance.activate(
        draft_id,
        evaluation_results=draft.evaluation_results,
    )
    return activated.status


def load_skill_eval_cases(path: Path) -> list[SkillEvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("skill eval case file must contain a non-empty cases list")
    cases = []
    for item in raw_cases:
        if not isinstance(item, dict):
            raise ValueError("skill eval cases must be objects")
        case_id = str(item.get("id") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        terms = item.get("required_output_terms") or []
        if not case_id or not prompt or not isinstance(terms, list):
            raise ValueError("each skill eval case requires id, prompt, and a term list")
        cases.append(
            SkillEvalCase(
                id=case_id,
                prompt=prompt,
                required_output_terms=tuple(str(term) for term in terms),
            )
        )
    return cases


def _governance() -> SkillGovernanceService:
    return SkillGovernanceService(
        FileSkillStore(get_skills_dir()),
        gate=SkillPromotionGate(required_suites=("skill_ab",)),
    )


def _model_config_fingerprint(
    *,
    model_settings: ModelSettings,
    runtime_settings: RuntimeSettings,
    system_prompt: str | None,
) -> str:
    payload = {
        "base_url": model_settings.base_url or "",
        "context_limit_tokens": model_settings.context_limit_tokens,
        "max_iterations": runtime_settings.max_iterations,
        "model": model_settings.model,
        "system_prompt": system_prompt or "",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode('utf-8')).hexdigest()}"
