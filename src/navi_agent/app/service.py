from __future__ import annotations

from collections.abc import Callable

from navi_agent.evolution import (
    BackgroundSkillReviewStatus,
    CandidateStore,
    EvalCase,
    EvalCaseStore,
    EvolutionCandidate,
    FileSkillStore,
    JsonlReviewRunStore,
    PromptOverlayStore,
    ReviewAgentService,
    ReviewTriggerPolicy,
    SkillAdmissionValidator,
    SkillGovernanceService,
    SkillProvenanceStore,
    SkillUsageStore,
)
from navi_agent.memory import MemoryStore
from navi_agent.events import RuntimeEventSubscriber
from navi_agent.runtime import (
    AgentRuntime,
    BackgroundTask,
    JsonPendingInteractionStore,
    Message,
    PendingInteraction,
    RuntimeResult,
    RuntimeRunState,
    SessionSummary,
)
from navi_agent.telemetry import RuntimeTrace

from .conversation_service import AppRequest, ConversationService
from .evolution_service import EvolutionService
from .session_query_service import SessionQueryService


class ApplicationService:
    """Compatibility facade over application-level use-case services."""

    def __init__(
        self,
        runtime: AgentRuntime,
        default_system_prompt: str | None = None,
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
        interaction_store: JsonPendingInteractionStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._default_system_prompt = default_system_prompt
        self._evolution = EvolutionService(
            runtime=runtime,
            candidate_store=candidate_store,
            eval_case_store=eval_case_store,
            prompt_overlay_store=prompt_overlay_store,
            skill_store=skill_store,
            skill_governance=skill_governance,
            skill_admission_validator=skill_admission_validator,
            skill_provenance_store=skill_provenance_store,
            skill_usage_store=skill_usage_store,
            memory_store=memory_store,
            review_agent_service=review_agent_service,
            review_run_store=review_run_store,
            review_trigger_policy=review_trigger_policy,
        )
        self._conversation = ConversationService(
            runtime,
            default_system_prompt=default_system_prompt,
            interaction_store=interaction_store,
            before_online_run=self._evolution.prepare_online_run,
            after_online_run=self._evolution.observe_runtime_result,
        )
        self._sessions = SessionQueryService(runtime)

        # Preserve the small set of legacy attributes used by integrations.
        self._candidate_store = candidate_store
        self._eval_case_store = eval_case_store
        self._prompt_overlay_store = prompt_overlay_store

    @property
    def _background_skill_review(self):
        return self._evolution._background_skill_review

    @_background_skill_review.setter
    def _background_skill_review(self, worker) -> None:
        self._evolution._background_skill_review = worker

    def handle(
        self,
        request: AppRequest,
        *,
        event_subscribers: list[RuntimeEventSubscriber] | None = None,
    ) -> RuntimeResult:
        return self._conversation.handle(
            request,
            event_subscribers=event_subscribers,
        )

    def cancel_session(self, session_id: str, *, reason: str = "user_requested") -> bool:
        return self._conversation.cancel_session(session_id, reason=reason)

    def is_session_active(self, session_id: str) -> bool:
        return self._conversation.is_session_active(session_id)

    def get_run_state(self, session_id: str) -> RuntimeRunState | None:
        return self._conversation.get_run_state(session_id)

    def resolve_interaction(
        self,
        session_id: str,
        *,
        approved: bool,
    ) -> PendingInteraction | None:
        return self._conversation.resolve_interaction(session_id, approved=approved)

    def add_background_task_listener(
        self,
        listener: Callable[[BackgroundTask], None],
    ) -> bool:
        return self._conversation.add_background_task_listener(listener)

    def get_latest_trace(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> RuntimeTrace | None:
        return self._sessions.get_latest_trace(
            session_id=session_id,
            user_id=user_id,
        )

    def has_session(self, session_id: str, user_id: str) -> bool:
        return self._sessions.has_session(session_id, user_id)

    def list_sessions(self, user_id: str, limit: int = 10) -> list[SessionSummary]:
        return self._sessions.list_sessions(user_id, limit)

    def get_session_messages(
        self,
        session_id: str,
        user_id: str,
    ) -> list[Message]:
        return self._sessions.get_session_messages(session_id, user_id)

    def list_background_tasks(
        self,
        session_id: str,
        user_id: str,
    ) -> list[BackgroundTask]:
        return self._sessions.list_background_tasks(session_id, user_id)

    def get_session_traces(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
    ) -> list[RuntimeTrace]:
        return self._sessions.get_session_traces(session_id, user_id=user_id)

    def add_candidate(self, candidate: EvolutionCandidate) -> None:
        self._evolution.add_candidate(candidate)

    def get_candidate(self, candidate_id: str) -> EvolutionCandidate | None:
        return self._evolution.get_candidate(candidate_id)

    def update_candidate_status(
        self,
        candidate_id: str,
        status: str,
        *,
        review_note: str | None = None,
    ) -> EvolutionCandidate | None:
        return self._evolution.update_candidate_status(
            candidate_id,
            status,
            review_note=review_note,
        )

    def apply_candidate(
        self,
        candidate_id: str,
        *,
        review_note: str | None = None,
    ) -> EvolutionCandidate | None:
        return self._evolution.apply_candidate(
            candidate_id,
            review_note=review_note,
        )

    def rollback_candidate(
        self,
        candidate_id: str,
        *,
        status: str = "regressed_after_apply",
        review_note: str | None = None,
    ) -> EvolutionCandidate | None:
        return self._evolution.rollback_candidate(
            candidate_id,
            status=status,
            review_note=review_note,
        )

    def finalize_candidate_evaluation(
        self,
        candidate_id: str,
        eval_case: EvalCase,
        *,
        report_path: str,
    ) -> EvolutionCandidate | None:
        return self._evolution.finalize_candidate_evaluation(
            candidate_id,
            eval_case,
            report_path=report_path,
        )

    def list_candidates(
        self,
        limit: int | None = None,
        *,
        status: str | None = None,
    ) -> list[EvolutionCandidate]:
        return self._evolution.list_candidates(limit, status=status)

    def add_eval_case(self, eval_case: EvalCase) -> None:
        self._evolution.add_eval_case(eval_case)

    def list_eval_cases(self, limit: int | None = None) -> list[EvalCase]:
        return self._evolution.list_eval_cases(limit)

    def wait_for_background_reviews(self) -> None:
        self._evolution.wait_for_background_reviews()

    def get_background_review_status(self) -> BackgroundSkillReviewStatus | None:
        return self._evolution.get_background_review_status()

    def close(self) -> None:
        self._evolution.wait_for_background_reviews()
        self._runtime.close()
