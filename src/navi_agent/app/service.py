from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from navi_agent.evolution import (
    BackgroundReviewTask,
    BackgroundSkillReviewStatus,
    BackgroundSkillReviewWorker,
    CandidateStore,
    EvolutionCandidate,
    EvolutionEngine,
    NudgeReviewTriggerPolicy,
    SimpleEvaluator,
    PromptOverlayStore,
    EvalCase,
    EvalCaseStore,
    FileSkillStore,
    SkillProvenanceStore,
    ReviewAgentService,
    SkillReviewEvidence,
    SkillReviewService,
    SkillUsageStore,
    ReviewTriggerPolicy,
)
from navi_agent.memory import MemoryStore
from navi_agent.runtime import AgentRuntime, RuntimeResult
from navi_agent.telemetry import RuntimeTrace


@dataclass(slots=True)
class AppRequest:
    user_id: str
    message: str
    session_id: str | None = None
    system_prompt: str | None = None
    auto_propose_eval_case: bool = True
    auto_propose_skill: bool = True


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
        skill_provenance_store: SkillProvenanceStore | None = None,
        skill_usage_store: SkillUsageStore | None = None,
        memory_store: MemoryStore | None = None,
        review_agent_service: ReviewAgentService | None = None,
        skill_review_service: SkillReviewService | None = None,
        review_trigger_policy: ReviewTriggerPolicy | None = None,
    ) -> None:
        self._runtime = runtime
        self._default_system_prompt = default_system_prompt
        self._candidate_store = candidate_store
        self._eval_case_store = eval_case_store
        self._prompt_overlay_store = prompt_overlay_store
        self._skill_store = skill_store
        self._skill_provenance_store = skill_provenance_store
        self._skill_usage_store = skill_usage_store
        self._memory_store = memory_store
        self._review_agent_service = review_agent_service
        self._skill_review_service = skill_review_service
        self._review_trigger_policy = review_trigger_policy or NudgeReviewTriggerPolicy()
        self._evaluator = SimpleEvaluator()
        self._evolution_engine = EvolutionEngine()
        self._background_skill_review = (
            BackgroundSkillReviewWorker(review_trace=self._run_background_review_task)
            if skill_review_service is not None or review_agent_service is not None
            else None
        )

    def handle(self, request: AppRequest) -> RuntimeResult:
        session_id = request.session_id or self._new_session_id()
        system_prompt = request.system_prompt
        if system_prompt is None:
            system_prompt = self._default_system_prompt

        self._hydrate_review_trigger(session_id=session_id, user_id=request.user_id)
        result = self._runtime.run_conversation(
            session_id=session_id,
            user_id=request.user_id,
            user_message=request.message,
            system_prompt=system_prompt,
        )
        if request.auto_propose_eval_case or request.auto_propose_skill:
            self._maybe_add_runtime_candidates(
                result=result,
                session_id=result.session_id,
                user_id=request.user_id,
                auto_propose_eval_case=request.auto_propose_eval_case,
                auto_propose_skill=request.auto_propose_skill,
            )
        return result

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
        if candidate.target == "prompt":
            if self._prompt_overlay_store is None:
                return None
            self._prompt_overlay_store.append_candidate(candidate)
            note = review_note or "applied prompt overlay"
        elif candidate.target == "skill":
            if self._skill_store is None:
                return None
            candidate.status = "accepted"
            skill = self._evolution_engine.apply_skill_candidate(
                candidate,
                skill_store=self._skill_store,
            )
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
        if candidate.target != "skill":
            return None
        if self._skill_store is None:
            return None
        skill_name = (candidate.metadata or {}).get("skill_name")
        if not isinstance(skill_name, str) or not skill_name.strip():
            return None
        self._skill_store.remove(skill_name)
        if self._skill_provenance_store is not None:
            self._skill_provenance_store.remove(skill_name)
        if self._skill_usage_store is not None:
            self._skill_usage_store.record_archive(skill_name)
        return self.update_candidate_status(
            candidate_id,
            status,
            review_note=review_note or f"rolled back skill {skill_name}",
        )

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
        auto_propose_eval_case: bool,
        auto_propose_skill: bool,
    ) -> None:
        if self._candidate_store is None:
            return
        trace = self._runtime.get_latest_trace(session_id=session_id, user_id=user_id)
        if trace is None:
            return
        if auto_propose_eval_case:
            candidate = self._evaluator.build_eval_case_candidate(trace)
            if candidate is not None:
                self.add_candidate(candidate)
        if auto_propose_skill:
            decision = self._review_trigger_policy.decide(
                trace,
                memory_available=self._review_agent_service is not None,
                skill_available=self._review_agent_service is not None
                or self._skill_review_service is not None,
            )
            if self._background_skill_review is not None and (
                (decision.review_memory and self._review_agent_service is not None)
                or (
                    decision.review_skill
                    and (
                        self._review_agent_service is not None
                        or self._skill_review_service is not None
                    )
                )
            ):
                review_with_agent = (
                    self._review_agent_service is not None
                    and (
                        (decision.review_memory and self._review_agent_service is not None)
                        or (decision.review_skill and self._review_agent_service is not None)
                    )
                )
                self._background_skill_review.submit(
                    trace,
                    review_evidence=(
                        self._build_skill_review_evidence(
                            trace,
                            result=result,
                        )
                        if review_with_agent
                        or (decision.review_skill and self._skill_review_service is not None)
                        else None
                    ),
                    review_memory=decision.review_memory and self._review_agent_service is not None,
                    review_skill=decision.review_skill
                    and (
                        self._review_agent_service is not None
                        or self._skill_review_service is not None
                    ),
                )
            elif self._background_skill_review is None:
                self._propose_and_add_skill_candidate(trace)

    def _hydrate_review_trigger(self, *, session_id: str, user_id: str) -> None:
        hydrate = getattr(self._review_trigger_policy, "hydrate", None)
        if not callable(hydrate):
            return
        traces = self._runtime.get_session_traces(session_id, user_id=user_id)
        hydrate(
            traces,
            memory_available=self._review_agent_service is not None,
            skill_available=self._review_agent_service is not None
            or self._skill_review_service is not None,
        )

    def wait_for_background_reviews(self) -> None:
        if self._background_skill_review is None:
            return
        self._background_skill_review.drain()

    def get_background_review_status(self) -> BackgroundSkillReviewStatus | None:
        if self._background_skill_review is None:
            return None
        return self._background_skill_review.status()

    def _propose_and_add_skill_candidate(
        self,
        trace: RuntimeTrace | SkillReviewEvidence,
    ) -> None:
        if self._skill_review_service is not None:
            candidate = self._skill_review_service.propose_candidate(trace)
            if candidate is not None:
                self._apply_background_skill_candidate(candidate)
            return
        else:
            candidate = self._evolution_engine.propose_skill_candidate(trace)
        if candidate is not None and not self._skill_exists(candidate):
            self.add_candidate(candidate)

    def _apply_background_skill_candidate(self, candidate: EvolutionCandidate) -> None:
        if self._skill_store is None:
            return
        operation = str((candidate.metadata or {}).get("operation") or "create").strip()
        if operation != "update" and self._skill_exists(candidate):
            return
        candidate.status = "accepted"
        skill = self._evolution_engine.apply_skill_candidate(
            candidate,
            skill_store=self._skill_store,
        )
        if skill is None:
            return
        if self._skill_provenance_store is not None:
            self._skill_provenance_store.mark_agent_created(
                skill_name=skill.name,
                candidate=candidate,
            )
        self._record_skill_usage(skill.name, candidate=candidate)

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
            result = self._review_agent_service.review_and_write(
                task.review_evidence,
                review_memory=task.review_memory,
                review_skill=task.review_skill,
            )
            self._record_review_agent_skill_actions(result)
            return
        if task.review_skill:
            if task.review_evidence is None:
                return
            evidence = task.review_evidence
            review_and_write = getattr(self._skill_review_service, "review_and_write", None)
            if callable(review_and_write):
                result = review_and_write(evidence)
                self._record_review_agent_skill_actions(result)
            else:
                self._propose_and_add_skill_candidate(evidence)

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

    def _record_review_agent_skill_actions(self, result: RuntimeResult) -> None:
        for tool_result in result.tool_results:
            if tool_result.name != "skill_manage" or tool_result.status != "success":
                continue
            action = str(tool_result.structured_content.get("action") or "").strip()
            skill_name = str(tool_result.structured_content.get("skill_name") or "").strip()
            if not action or not skill_name:
                continue
            if action == "create":
                if self._skill_provenance_store is not None:
                    self._skill_provenance_store.mark_agent_created(
                        skill_name=skill_name,
                        candidate=EvolutionCandidate(
                            target="skill",
                            summary=f"Background review agent created skill `{skill_name}`",
                            rationale="Tool-using skill review agent wrote this skill.",
                            metadata={"skill_name": skill_name, "reviewer": "agent"},
                            status="applied",
                        ),
                    )
                if self._skill_usage_store is not None:
                    self._skill_usage_store.record_create(skill_name)
            elif action == "append":
                if self._skill_usage_store is not None:
                    self._skill_usage_store.record_update(skill_name)

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

    def _skill_exists(self, candidate: EvolutionCandidate) -> bool:
        if self._skill_store is None:
            return False
        skill_name = (candidate.metadata or {}).get("skill_name")
        if not isinstance(skill_name, str) or not skill_name.strip():
            return False
        return self._skill_store.get(skill_name) is not None

    @staticmethod
    def _new_session_id() -> str:
        return uuid4().hex
