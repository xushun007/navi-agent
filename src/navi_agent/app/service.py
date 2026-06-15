from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from navi_agent.evolution import CandidateStore, WorkflowEvolutionSample, WorkflowSampleStore, EvolutionCandidate
from navi_agent.runtime import AgentRuntime, RuntimeResult
from navi_agent.telemetry import RuntimeTrace


@dataclass(slots=True)
class AppRequest:
    user_id: str
    message: str
    session_id: str | None = None
    system_prompt: str | None = None


class ApplicationService:
    def __init__(
        self,
        runtime: AgentRuntime,
        default_system_prompt: str | None = None,
        candidate_store: CandidateStore | None = None,
        workflow_sample_store: WorkflowSampleStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._default_system_prompt = default_system_prompt
        self._candidate_store = candidate_store
        self._workflow_sample_store = workflow_sample_store

    def handle(self, request: AppRequest) -> RuntimeResult:
        session_id = request.session_id or self._new_session_id()
        system_prompt = request.system_prompt
        if system_prompt is None:
            system_prompt = self._default_system_prompt

        return self._runtime.run_conversation(
            session_id=session_id,
            user_id=request.user_id,
            user_message=request.message,
            system_prompt=system_prompt,
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
        return self._candidate_store.update_status(
            candidate_id,
            status,
            review_note=review_note,
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

    def add_workflow_sample(self, sample: WorkflowEvolutionSample) -> None:
        if self._workflow_sample_store is None:
            return
        self._workflow_sample_store.add(sample)

    def list_workflow_samples(self, limit: int | None = None) -> list[WorkflowEvolutionSample]:
        if self._workflow_sample_store is None:
            return []
        return self._workflow_sample_store.list_recent(limit=limit)

    @staticmethod
    def _new_session_id() -> str:
        return uuid4().hex
