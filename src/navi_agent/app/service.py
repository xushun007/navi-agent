from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from navi_agent.evolution import (
    BackgroundReviewTask,
    BackgroundSkillReviewStatus,
    BackgroundSkillReviewWorker,
    CandidateStore,
    EvolutionCandidate,
    EvolutionGate,
    EvolutionRollback,
    NudgeReviewTriggerPolicy,
    SimpleEvaluator,
    PromptOverlayStore,
    EvalCase,
    EvalCaseStore,
    FileSkillStore,
    SkillDraftEvaluator,
    SkillDraftProvenance,
    SkillGovernanceService,
    JsonlReviewRunStore,
    SkillProvenanceStore,
    ReviewAgentService,
    ReviewRunRecord,
    ReviewToolResultRecord,
    SkillReviewEvidence,
    SkillUsageStore,
    ReviewTriggerPolicy,
)
from navi_agent.memory import MemoryStore
from navi_agent.events import RuntimeEvent, RuntimeEventPublisher, RuntimeEventSubscriber
from navi_agent.runtime import (
    ActiveRunRegistry,
    AgentRuntime,
    BackgroundTask,
    JsonPendingInteractionStore,
    Message,
    PendingInteraction,
    RuntimeResult,
    RuntimeMode,
    RuntimeRunState,
    RunStateTracker,
    SessionSummary,
)
from navi_agent.telemetry import RuntimeTrace


@dataclass(slots=True)
class AppRequest:
    user_id: str
    message: str
    session_id: str | None = None
    system_prompt: str | None = None
    mode: RuntimeMode = RuntimeMode.ONLINE
    source: str = "console"


class ApplicationService:
    _INACTIVE_CANDIDATE_STATUSES = {"superseded", "archived"}
    _VALIDATED_CANDIDATE_STATUSES = {
        "verified",
        "no_improvement",
        "regressed_after_apply",
    }

    def __init__(
        self,
        runtime: AgentRuntime,
        default_system_prompt: str | None = None,
        candidate_store: CandidateStore | None = None,
        eval_case_store: EvalCaseStore | None = None,
        prompt_overlay_store: PromptOverlayStore | None = None,
        skill_store: FileSkillStore | None = None,
        skill_governance: SkillGovernanceService | None = None,
        skill_evaluator: SkillDraftEvaluator | None = None,
        skill_provenance_store: SkillProvenanceStore | None = None,
        skill_usage_store: SkillUsageStore | None = None,
        memory_store: MemoryStore | None = None,
        review_agent_service: ReviewAgentService | None = None,
        review_run_store: JsonlReviewRunStore | None = None,
        review_trigger_policy: ReviewTriggerPolicy | None = None,
        interaction_store: JsonPendingInteractionStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._active_runs = ActiveRunRegistry()
        self._run_states = RunStateTracker()
        self._default_system_prompt = default_system_prompt
        self._candidate_store = candidate_store
        self._eval_case_store = eval_case_store
        self._prompt_overlay_store = prompt_overlay_store
        self._skill_store = skill_store
        self._skill_governance = skill_governance
        self._skill_evaluator = skill_evaluator
        self._skill_provenance_store = skill_provenance_store
        self._skill_usage_store = skill_usage_store
        self._memory_store = memory_store
        self._review_agent_service = review_agent_service
        self._review_run_store = review_run_store
        self._review_trigger_policy = review_trigger_policy or NudgeReviewTriggerPolicy()
        self._interaction_store = interaction_store
        self._evaluator = SimpleEvaluator()
        self._background_skill_review = (
            BackgroundSkillReviewWorker(review_trace=self._run_background_review_task)
            if review_agent_service is not None
            else None
        )

    def handle(
        self,
        request: AppRequest,
        *,
        event_subscribers: list[RuntimeEventSubscriber] | None = None,
    ) -> RuntimeResult:
        session_id = request.session_id or self._new_session_id()
        system_prompt = request.system_prompt
        if system_prompt is None:
            system_prompt = self._default_system_prompt

        resume_interaction = None
        if self._interaction_store is not None:
            self._publish_expired_interactions(
                session_id=session_id,
                event_subscribers=event_subscribers,
            )
            pending = self._interaction_store.get_pending(session_id)
            if pending is not None and pending.kind == "clarification":
                self._interaction_store.resolve_clarification(
                    session_id,
                    response=request.message,
                )
            resume_interaction = self._interaction_store.get_resolved(session_id)

        if request.mode is RuntimeMode.ONLINE:
            self._hydrate_review_trigger(session_id=session_id, user_id=request.user_id)
        cancellation_token = self._active_runs.start(session_id)
        try:
            result = self._runtime.run_conversation(
                session_id=session_id,
                user_id=request.user_id,
                user_message=request.message,
                system_prompt=system_prompt,
                source=request.source,
                mode=request.mode,
                event_subscribers=[self._run_states, *(event_subscribers or [])],
                cancellation_token=cancellation_token,
                resume_interaction=resume_interaction,
            )
        finally:
            self._active_runs.finish(session_id, cancellation_token)
        if self._interaction_store is not None and result.status == "awaiting_input":
            self._attach_pending_tool_call(result)
        if self._interaction_store is not None and resume_interaction is not None:
            self._interaction_store.complete(resume_interaction.interaction_id)
        if request.mode is RuntimeMode.ONLINE:
            self._maybe_add_runtime_candidates(
                result=result,
                session_id=result.session_id,
                user_id=request.user_id,
            )
        return result

    def cancel_session(self, session_id: str, *, reason: str = "user_requested") -> bool:
        return self._active_runs.cancel(session_id, reason)

    def is_session_active(self, session_id: str) -> bool:
        return self._active_runs.is_active(session_id)

    def get_run_state(self, session_id: str) -> RuntimeRunState | None:
        return self._run_states.get(session_id)

    def resolve_interaction(
        self,
        session_id: str,
        *,
        approved: bool,
    ) -> PendingInteraction | None:
        if self._interaction_store is None:
            return None
        self._publish_expired_interactions(session_id=session_id)
        return self._interaction_store.resolve(session_id, approved=approved)

    def _publish_expired_interactions(
        self,
        *,
        session_id: str,
        event_subscribers: list[RuntimeEventSubscriber] | None = None,
    ) -> None:
        if self._interaction_store is None:
            return
        subscribers = [self._run_states, *(event_subscribers or [])]
        for interaction in self._interaction_store.expire(session_id):
            event = RuntimeEvent(
                session_id=interaction.session_id,
                user_id=interaction.user_id,
                run_id=f"interaction:{interaction.interaction_id}",
                sequence=1,
                kind="observation",
                source="runtime",
                name="runtime.interaction_expired",
                item_id=interaction.interaction_id,
                metadata={
                    "status": "expired",
                    "interaction_id": interaction.interaction_id,
                    "interaction_kind": interaction.kind,
                    "origin_run_id": interaction.run_id,
                    "reason": "interaction_ttl_elapsed",
                },
            )
            publish = getattr(self._runtime, "publish_runtime_event", None)
            if callable(publish):
                publish(event, subscribers)
            else:
                RuntimeEventPublisher(subscribers).publish(event)

    def _attach_pending_tool_call(self, result: RuntimeResult) -> None:
        if self._interaction_store is None:
            return
        pending_result = next(
            (
                item
                for item in result.tool_results
                if item.structured_content.get("interaction_pending") is True
            ),
            None,
        )
        if pending_result is None:
            return
        interaction_id = pending_result.structured_content.get("interaction_id")
        if not isinstance(interaction_id, str) or not interaction_id:
            return
        tool_call = next(
            (
                tool_call
                for message in reversed(result.messages)
                for tool_call in message.tool_calls
                if tool_call.id == pending_result.tool_call_id
            ),
            None,
        )
        if tool_call is None:
            return
        self._interaction_store.attach_tool_call(
            interaction_id,
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
        )

    def get_latest_trace(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> RuntimeTrace | None:
        return self._runtime.get_latest_trace(
            session_id=session_id,
            user_id=user_id,
        )

    def add_background_task_listener(self, listener: Callable[[BackgroundTask], None]) -> bool:
        return self._runtime.add_background_task_listener(listener)

    def has_session(self, session_id: str, user_id: str) -> bool:
        return self._runtime.has_session(session_id, user_id)

    def list_sessions(self, user_id: str, limit: int = 10) -> list[SessionSummary]:
        return self._runtime.list_sessions(user_id, limit)

    def get_session_messages(
        self,
        session_id: str,
        user_id: str,
    ) -> list[Message]:
        return self._runtime.get_session_messages(session_id, user_id)

    def list_background_tasks(
        self,
        session_id: str,
        user_id: str,
    ) -> list[BackgroundTask]:
        return self._runtime.list_background_tasks(session_id, user_id)

    def get_session_traces(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
    ) -> list[RuntimeTrace]:
        return self._runtime.get_session_traces(
            session_id=session_id,
            user_id=user_id,
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
            self._prompt_overlay_store.append_candidate(candidate)
            note = review_note or "applied prompt overlay"
        elif candidate.target == "skill":
            if self._skill_governance is None or self._skill_evaluator is None:
                return None
            metadata = candidate.metadata or {}
            skill_name = str(metadata.get("skill_name") or "").strip()
            provenance = SkillDraftProvenance(
                review_run_id=candidate.candidate_id,
                source_session_id=str(metadata.get("source_session_id") or ""),
                source_trace_id=str(metadata.get("source_trace_id") or candidate.candidate_id),
                evidence_ids=(candidate.candidate_id,),
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
                decision = self._skill_governance.evaluate_and_promote(
                    draft.draft_id,
                    evaluator=self._skill_evaluator,
                )
            except ValueError:
                return None
            if decision.status != "promoted":
                return self.update_candidate_status(
                    candidate_id,
                    decision.status,
                    review_note=decision.decision_reason,
                )
            skill = self._skill_store.get(skill_name) if self._skill_store is not None else None
            if skill is None:
                return None
            if self._skill_provenance_store is not None:
                self._skill_provenance_store.mark_agent_created(
                    skill_name=skill.name,
                    candidate=candidate,
                )
            self._record_skill_usage(skill.name, candidate=candidate)
            note = review_note or f"applied skill {skill.name}"
        else:
            return None
        return self.update_candidate_status(
            candidate_id,
            "applied",
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
        skill_name = (candidate.metadata or {}).get("skill_name")
        if not isinstance(skill_name, str) or not skill_name.strip():
            return None
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
        if candidate is None or candidate.status != "applied":
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
            return self.update_candidate_status(
                candidate_id,
                "verified",
                review_note=note,
            )
        return self.rollback_candidate(
            candidate_id,
            status=gate_result.status,
            review_note=f"rolled back after evolution gate: {note}",
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

    def _maybe_add_runtime_candidates(
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

    def _hydrate_review_trigger(self, *, session_id: str, user_id: str) -> None:
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
            if task.review_skill and self._has_promoted_skill_write(result):
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
            promotion_status = str(
                tool_result.structured_content.get("promotion_status") or ""
            )
            if promotion_status != "promoted":
                continue
            if action == "draft_create":
                if self._skill_provenance_store is not None:
                    self._skill_provenance_store.mark_agent_created(
                        skill_name=skill_name,
                        candidate=EvolutionCandidate(
                            target="skill",
                            summary=f"Background review agent created skill `{skill_name}`",
                            rationale="Tool-using skill review agent wrote this skill.",
                            evidence_ids=[trace.trace_id],
                            expected_outcome="Preserve a reviewed procedure as reusable skill memory.",
                            source_trace_id=trace.trace_id,
                            metadata={"skill_name": skill_name, "reviewer": "agent"},
                            status="applied",
                        ),
                    )
                if self._skill_usage_store is not None:
                    self._skill_usage_store.record_create(skill_name)
            elif action == "draft_append":
                if self._skill_usage_store is not None:
                    self._skill_usage_store.record_update(skill_name)

    @staticmethod
    def _has_promoted_skill_write(result: RuntimeResult) -> bool:
        return any(
            tool_result.name == "skill_manage"
            and tool_result.status == "success"
            and tool_result.structured_content.get("promotion_status") == "promoted"
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

    @staticmethod
    def _new_session_id() -> str:
        return uuid4().hex
