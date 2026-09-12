from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from navi_agent.evolution import (
    BackgroundReviewTask,
    BackgroundSkillReviewStatus,
    BackgroundSkillReviewWorker,
    CandidateStore,
    EvalCase,
    EvalCaseStore,
    EvolutionCandidate,
    EvolutionGate,
    EvolutionRollback,
    FileSkillStore,
    JsonlReviewRunStore,
    NudgeReviewTriggerPolicy,
    PromptOverlayStore,
    ReviewAgentService,
    ReviewRunRecord,
    ReviewToolResultRecord,
    ReviewTriggerPolicy,
    SimpleEvaluator,
    SkillAdmissionValidator,
    SkillDraftProvenance,
    SkillGovernanceService,
    SkillProvenanceStore,
    SkillReviewEvidence,
    SkillUsageStore,
)
from navi_agent.memory import MemoryStore
from navi_agent.runtime import AgentRuntime, RuntimeResult
from navi_agent.telemetry import RuntimeTrace

logger = logging.getLogger(__name__)


class EvolutionService:
    _INACTIVE_CANDIDATE_STATUSES = {"superseded", "archived"}
    _VALIDATED_CANDIDATE_STATUSES = {
        "verified",
        "no_improvement",
        "regressed_after_apply",
    }

    def __init__(
        self,
        runtime: AgentRuntime,
        candidate_store: CandidateStore | None = None,
        eval_case_store: EvalCaseStore | None = None,
        prompt_overlay_store: PromptOverlayStore | None = None,
        skill_store: FileSkillStore | None = None,
        skill_governance: SkillGovernanceService | None = None,
        skill_admission_validator: SkillAdmissionValidator | None = None,
        skill_provenance_store: SkillProvenanceStore | None = None,
        skill_usage_store: SkillUsageStore | None = None,
        memory_store: MemoryStore | None = None,
        review_agent_service: ReviewAgentService | None = None,
        review_run_store: JsonlReviewRunStore | None = None,
        review_trigger_policy: ReviewTriggerPolicy | None = None,
    ) -> None:
        self._runtime = runtime
        self._candidate_store = candidate_store
        self._eval_case_store = eval_case_store
        self._prompt_overlay_store = prompt_overlay_store
        self._skill_store = skill_store
        self._skill_governance = skill_governance
        self._skill_admission_validator = skill_admission_validator
        self._skill_provenance_store = skill_provenance_store
        self._skill_usage_store = skill_usage_store
        self._memory_store = memory_store
        self._review_agent_service = review_agent_service
        self._review_run_store = review_run_store
        self._review_trigger_policy = review_trigger_policy or NudgeReviewTriggerPolicy()
        self._evaluator = SimpleEvaluator()
        self._background_skill_review = (
            BackgroundSkillReviewWorker(review_trace=self._run_background_review_task)
            if review_agent_service is not None
            else None
        )

    def add_candidate(self, candidate: EvolutionCandidate) -> None:
        if self._candidate_store is None:
            return
        for existing in self._find_archivable_candidates(candidate):
            self._candidate_store.update_status(
                existing.candidate_id,
                "archived",
                review_note=f"archived when new candidate {candidate.candidate_id} entered scope",
            )
        for existing in self._find_superseded_candidates(candidate):
            self._candidate_store.update_status(
                existing.candidate_id,
                "superseded",
                review_note=f"superseded by {candidate.candidate_id}",
            )
        self._candidate_store.add(candidate)

    def get_candidate(self, candidate_id: str) -> EvolutionCandidate | None:
        if self._candidate_store is None:
            return None
        return self._candidate_store.get(candidate_id)

    def update_candidate_status(
        self,
        candidate_id: str,
        status: str,
        *,
        review_note: str | None = None,
    ) -> EvolutionCandidate | None:
        if self._candidate_store is None:
            return None
        updated = self._candidate_store.update_status(
            candidate_id,
            status,
            review_note=review_note,
        )
        if updated is None:
            return None
        if status in self._VALIDATED_CANDIDATE_STATUSES:
            for existing in self._find_archivable_candidates(updated):
                self._candidate_store.update_status(
                    existing.candidate_id,
                    "archived",
                    review_note=f"archived after {updated.candidate_id} reached {status}",
                )
        return updated

    def apply_candidate(
        self,
        candidate_id: str,
        *,
        review_note: str | None = None,
    ) -> EvolutionCandidate | None:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            return None
        if candidate.status != "accepted":
            return None
        if candidate.target == "prompt":
            if self._prompt_overlay_store is None:
                return None
            note = review_note or "staged prompt candidate"
        elif candidate.target == "skill":
            if self._skill_governance is None or self._skill_admission_validator is None:
                return None
            metadata = candidate.metadata or {}
            skill_name = str(metadata.get("skill_name") or "").strip()
            provenance = SkillDraftProvenance(
                review_run_id=candidate.candidate_id,
                source_session_id=str(metadata.get("source_session_id") or ""),
                source_trace_id=str(metadata.get("source_trace_id") or candidate.candidate_id),
                evidence_ids=(candidate.candidate_id,),
                source_kind=str(metadata.get("source_kind") or "agent"),
                source_uri=str(metadata.get("source_uri") or ""),
            )
            operation = str(metadata.get("operation") or "create").strip()
            try:
                if operation == "update":
                    draft = self._skill_governance.append_draft(
                        skill_name=skill_name,
                        section=str(metadata.get("section") or ""),
                        content=str(metadata.get("append_content") or ""),
                        provenance=provenance,
                    )
                else:
                    draft = self._skill_governance.create_draft(
                        skill_name=skill_name,
                        content=str(metadata.get("skill_content") or ""),
                        provenance=provenance,
                    )
                admission = self._skill_governance.admit(
                    draft.draft_id,
                    validator=self._skill_admission_validator,
                )
            except ValueError:
                return None
            if admission.status != "candidate":
                return self.update_candidate_status(
                    candidate_id,
                    admission.status,
                    review_note=admission.decision_reason,
                )
            candidate.metadata["draft_id"] = draft.draft_id
            candidate.metadata["source_kind"] = provenance.source_kind
            self._candidate_store.save(candidate)
            note = review_note or f"admitted skill draft {draft.draft_id}"
        else:
            return None
        return self.update_candidate_status(
            candidate_id,
            "staged",
            review_note=note,
        )

    def rollback_candidate(
        self,
        candidate_id: str,
        *,
        status: str = "regressed_after_apply",
        review_note: str | None = None,
    ) -> EvolutionCandidate | None:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            return None
        previous_status = candidate.status
        note = review_note or "rolled back candidate"
        if candidate.target == "prompt":
            if self._prompt_overlay_store is None:
                return None
            if previous_status == "staged":
                return self._record_candidate_rollback(
                    candidate,
                    status=status,
                    reason=note,
                    previous_status=previous_status,
                )
            if not self._prompt_overlay_store.rollback_candidate(candidate_id):
                return None
            note = review_note or "rolled back prompt overlay"
            return self._record_candidate_rollback(
                candidate,
                status=status,
                reason=note,
                previous_status=previous_status,
            )
        if candidate.target != "skill":
            return None
        if self._skill_store is None or self._skill_governance is None:
            return None
        metadata = candidate.metadata or {}
        skill_name = metadata.get("skill_name")
        if not isinstance(skill_name, str) or not skill_name.strip():
            return None
        draft_id = str(metadata.get("draft_id") or "")
        if previous_status == "staged" and draft_id:
            try:
                self._skill_governance.discard(draft_id, reason=note)
            except ValueError:
                return None
            return self._record_candidate_rollback(
                candidate,
                status=status,
                reason=note,
                previous_status=previous_status,
            )
        try:
            self._skill_governance.rollback(skill_name)
        except ValueError:
            return None
        if self._skill_provenance_store is not None and self._skill_store.get(skill_name) is None:
            self._skill_provenance_store.remove(skill_name)
        if self._skill_usage_store is not None:
            self._skill_usage_store.record_archive(skill_name)
        note = review_note or f"rolled back skill {skill_name}"
        return self._record_candidate_rollback(
            candidate,
            status=status,
            reason=note,
            previous_status=previous_status,
        )

    def finalize_candidate_evaluation(
        self,
        candidate_id: str,
        eval_case: EvalCase,
        *,
        report_path: str,
    ) -> EvolutionCandidate | None:
        candidate = self.get_candidate(candidate_id)
        if candidate is None or candidate.status != "staged":
            return None
        workflow_name = str((candidate.metadata or {}).get("workflow_name") or "")
        if workflow_name and workflow_name != eval_case.workflow_name:
            raise ValueError("candidate and eval case workflows do not match")

        gate_result = EvolutionGate().evaluate(eval_case, report_path=report_path)
        candidate.gate_result = gate_result
        if self._candidate_store is None:
            return None
        self._candidate_store.save(candidate)
        note = (
            f"workflow={gate_result.workflow_name} "
            f"score_delta={gate_result.score_delta} report={gate_result.report_path}"
        )
        if gate_result.status == "verified":
            if self._prompt_overlay_store is None:
                return None
            self._prompt_overlay_store.append_candidate(
                replace(candidate, status="verified")
            )
            return self.update_candidate_status(
                candidate_id,
                "verified",
                review_note=note,
            )
        return self._record_candidate_rollback(
            candidate,
            status=gate_result.status,
            reason=f"rejected staged candidate after evolution gate: {note}",
            previous_status="staged",
        )

    def _record_candidate_rollback(
        self,
        candidate: EvolutionCandidate,
        *,
        status: str,
        reason: str,
        previous_status: str,
    ) -> EvolutionCandidate | None:
        if self._candidate_store is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        candidate.status = status
        candidate.review_note = reason
        candidate.reviewed_at = now
        candidate.rollback = EvolutionRollback(
            reason=reason,
            rolled_back_at=now,
            previous_status=previous_status,
        )
        self._candidate_store.save(candidate)
        for existing in self._find_archivable_candidates(candidate):
            self._candidate_store.update_status(
                existing.candidate_id,
                "archived",
                review_note=f"archived after {candidate.candidate_id} reached {status}",
            )
        return candidate

    def list_candidates(
        self,
        limit: int | None = None,
        *,
        status: str | None = None,
    ) -> list[EvolutionCandidate]:
        if self._candidate_store is None:
            return []
        items = self._candidate_store.list_recent(limit=limit)
        if status is None:
            return items
        return [candidate for candidate in items if candidate.status == status]

    def add_eval_case(self, eval_case: EvalCase) -> None:
        if self._eval_case_store is None:
            return
        self._eval_case_store.add(eval_case)

    def list_eval_cases(self, limit: int | None = None) -> list[EvalCase]:
        if self._eval_case_store is None:
            return []
        return self._eval_case_store.list_recent(limit=limit)

    def observe_runtime_result(
        self,
        *,
        result: RuntimeResult,
        session_id: str,
        user_id: str,
    ) -> None:
        if result.status in {"cancelled", "superseded", "awaiting_input"}:
            return
        if self._candidate_store is None:
            return
        trace = self._runtime.get_latest_trace(session_id=session_id, user_id=user_id)
        if trace is None:
            return
        candidate = self._evaluator.build_eval_case_candidate(trace)
        if candidate is not None:
            self.add_candidate(candidate)
        decision = self._review_trigger_policy.decide(
            trace,
            memory_available=self._review_agent_service is not None,
            skill_available=self._review_agent_service is not None,
        )
        if self._background_skill_review is not None and (
            (decision.review_memory and self._review_agent_service is not None)
            or (decision.review_skill and self._review_agent_service is not None)
        ):
            submitted = self._background_skill_review.submit(
                trace,
                review_evidence=self._build_skill_review_evidence(
                    trace,
                    result=result,
                ),
                review_memory=decision.review_memory and self._review_agent_service is not None,
                review_skill=decision.review_skill and self._review_agent_service is not None,
            )
            if submitted:
                self._review_trigger_policy.acknowledge(trace, decision)

    def prepare_online_run(self, session_id: str, user_id: str) -> None:
        hydrate = getattr(self._review_trigger_policy, "hydrate", None)
        if not callable(hydrate):
            return
        traces = self._runtime.get_user_traces(user_id)
        hydrate(
            traces,
            session_id=session_id,
            user_id=user_id,
            memory_available=self._review_agent_service is not None,
            skill_available=self._review_agent_service is not None,
        )

    def wait_for_background_reviews(self) -> None:
        if self._background_skill_review is None:
            return
        self._background_skill_review.drain()

    def get_background_review_status(self) -> BackgroundSkillReviewStatus | None:
        if self._background_skill_review is None:
            return None
        return self._background_skill_review.status()

    def _record_skill_usage(self, skill_name: str, *, candidate: EvolutionCandidate) -> None:
        if self._skill_usage_store is None:
            return
        operation = str((candidate.metadata or {}).get("operation") or "create").strip()
        if operation == "update":
            self._skill_usage_store.record_update(skill_name)
        else:
            self._skill_usage_store.record_create(skill_name)

    def _run_background_review_task(self, task: BackgroundReviewTask) -> None:
        if self._review_agent_service is not None:
            if task.review_evidence is None:
                return
            review_run_id = uuid4().hex[:12]
            try:
                result = self._review_agent_service.review_and_write(
                    task.review_evidence,
                    review_memory=task.review_memory,
                    review_skill=task.review_skill,
                    review_run_id=review_run_id,
                )
            except Exception as error:
                self._record_review_run(
                    task,
                    status="error",
                    review_run_id=review_run_id,
                    error=str(error),
                )
                raise
            self._record_review_run(
                task,
                status=result.status,
                review_run_id=review_run_id,
                result=result,
            )
            self._record_review_agent_skill_actions(result, trace=task.trace)
            if task.review_skill and self._has_admitted_skill_write(result):
                self._review_trigger_policy.reset_skill(task.trace)

    def _build_skill_review_evidence(
        self,
        trace: RuntimeTrace,
        *,
        result: RuntimeResult,
    ) -> SkillReviewEvidence:
        return SkillReviewEvidence(
            session_id=trace.session_id,
            trace_id=trace.trace_id,
            user_id=trace.user_id,
            messages_snapshot=list(result.messages),
        )

    def _record_review_agent_skill_actions(
        self,
        result: RuntimeResult,
        *,
        trace: RuntimeTrace,
    ) -> None:
        for tool_result in result.tool_results:
            if tool_result.name != "skill_manage" or tool_result.status != "success":
                continue
            action = str(tool_result.structured_content.get("action") or "").strip()
            skill_name = str(tool_result.structured_content.get("skill_name") or "").strip()
            if not action or not skill_name:
                continue
            admission_status = str(
                tool_result.structured_content.get("admission_status") or ""
            )
            if admission_status != "candidate":
                continue
            logger.info(
                "Skill draft admitted for evaluation: skill=%s trace_id=%s",
                skill_name,
                trace.trace_id,
            )

    @staticmethod
    def _has_admitted_skill_write(result: RuntimeResult) -> bool:
        return any(
            tool_result.name == "skill_manage"
            and tool_result.status == "success"
            and tool_result.structured_content.get("admission_status") == "candidate"
            and tool_result.structured_content.get("action")
            in {"draft_create", "draft_append", "draft_attachment"}
            for tool_result in result.tool_results
        )

    def _record_review_run(
        self,
        task: BackgroundReviewTask,
        *,
        status: str,
        review_run_id: str,
        result: RuntimeResult | None = None,
        error: str = "",
    ) -> None:
        if self._review_run_store is None:
            return
        trace = task.trace
        tool_results = []
        memory_writes = []
        skill_writes = []
        for tool_result in result.tool_results if result is not None else []:
            action = str(tool_result.structured_content.get("action") or "").strip()
            record = ReviewToolResultRecord(
                name=tool_result.name,
                status=tool_result.status,
                action=action,
                structured_content=dict(tool_result.structured_content),
            )
            tool_results.append(record)
            if tool_result.status != "success":
                continue
            if tool_result.name == "memory" and action in {"add", "update", "remove"}:
                memory_writes.append(dict(tool_result.structured_content))
            if tool_result.name == "skill_manage" and action in {
                "draft_create",
                "draft_append",
                "draft_attachment",
            }:
                skill_writes.append(dict(tool_result.structured_content))
        self._review_run_store.add(
            ReviewRunRecord(
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                user_id=trace.user_id,
                review_memory=task.review_memory,
                review_skill=task.review_skill,
                status=status,
                review_run_id=review_run_id,
                review_session_id=result.session_id if result is not None else "",
                tool_results=tool_results,
                memory_writes=memory_writes,
                skill_writes=skill_writes,
                error=error,
            )
        )

    def _find_superseded_candidates(
        self,
        candidate: EvolutionCandidate,
    ) -> list[EvolutionCandidate]:
        if self._candidate_store is None:
            return []
        candidate_scope = self._candidate_scope(candidate)
        if candidate_scope is None:
            return []
        matches: list[EvolutionCandidate] = []
        for existing in self._candidate_store.list_recent(limit=None):
            if existing.candidate_id == candidate.candidate_id:
                continue
            if existing.status in self._INACTIVE_CANDIDATE_STATUSES:
                continue
            if existing.target != candidate.target:
                continue
            if existing.status in self._VALIDATED_CANDIDATE_STATUSES:
                continue
            if self._candidate_scope(existing) != candidate_scope:
                continue
            matches.append(existing)
        return matches

    def _find_archivable_candidates(
        self,
        candidate: EvolutionCandidate,
    ) -> list[EvolutionCandidate]:
        if self._candidate_store is None:
            return []
        candidate_scope = self._candidate_scope(candidate)
        if candidate_scope is None:
            return []
        matches: list[EvolutionCandidate] = []
        for existing in self._candidate_store.list_recent(limit=None):
            if existing.candidate_id == candidate.candidate_id:
                continue
            if existing.status in self._INACTIVE_CANDIDATE_STATUSES:
                continue
            if existing.target != candidate.target:
                continue
            if existing.status not in self._VALIDATED_CANDIDATE_STATUSES:
                continue
            if self._candidate_scope(existing) != candidate_scope:
                continue
            matches.append(existing)
        return matches

    @staticmethod
    def _candidate_scope(candidate: EvolutionCandidate) -> tuple[str, str] | None:
        metadata = candidate.metadata or {}
        if candidate.target == "skill":
            skill_name = metadata.get("skill_name")
            if isinstance(skill_name, str) and skill_name.strip():
                return "skill", skill_name
        workflow_name = metadata.get("workflow_name")
        task_name = metadata.get("task_name")
        if not isinstance(workflow_name, str) or not workflow_name.strip():
            return None
        if not isinstance(task_name, str) or not task_name.strip():
            return None
        return workflow_name, task_name
