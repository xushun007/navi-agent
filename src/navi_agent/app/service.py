from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from navi_agent.evolution import (
    CandidateStore,
    EvolutionCandidate,
    PromptOverlayStore,
    EvalCase,
    EvalCaseStore,
)
from navi_agent.runtime import AgentRuntime, RuntimeResult
from navi_agent.telemetry import RuntimeTrace


@dataclass(slots=True)
class AppRequest:
    user_id: str
    message: str
    session_id: str | None = None
    system_prompt: str | None = None


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
    ) -> None:
        self._runtime = runtime
        self._default_system_prompt = default_system_prompt
        self._candidate_store = candidate_store
        self._eval_case_store = eval_case_store
        self._prompt_overlay_store = prompt_overlay_store

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
        if candidate.target != "prompt":
            return None
        if self._prompt_overlay_store is None:
            return None
        self._prompt_overlay_store.append_candidate(candidate)
        return self.update_candidate_status(
            candidate_id,
            "applied",
            review_note=review_note or "applied prompt overlay",
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
