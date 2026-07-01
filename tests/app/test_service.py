import unittest

from navi_agent.app import AppRequest, ApplicationService
from navi_agent.evolution import EvolutionCandidate, EvalCase
from navi_agent.runtime import RuntimeResult
from navi_agent.telemetry import RuntimeTrace


class FakeRuntime:
    def __init__(self) -> None:
        self.calls = []
        self.latest_trace = None
        self.session_traces = []

    def run_conversation(self, session_id, user_id, user_message, system_prompt=None):
        self.calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "user_message": user_message,
                "system_prompt": system_prompt,
            }
        )
        return RuntimeResult(
            session_id=session_id,
            status="success",
            final_response="done",
        )

    def get_latest_trace(self, session_id=None, user_id=None):
        return self.latest_trace

    def get_session_traces(self, session_id, user_id=None):
        return self.session_traces


class FakeCandidateStore:
    def __init__(self) -> None:
        self.items = []

    def add(self, candidate) -> None:
        self.items.append(candidate)

    def list_recent(self, limit=None):
        items = list(reversed(self.items))
        if limit is None:
            return items
        return items[:limit]

    def get(self, candidate_id):
        for candidate in self.items:
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def update_status(self, candidate_id, status, review_note=None):
        candidate = self.get(candidate_id)
        if candidate is None:
            return None
        candidate.status = status
        candidate.review_note = review_note
        return candidate


class FakeEvalCaseStore:
    def __init__(self) -> None:
        self.items = []

    def add(self, eval_case) -> None:
        self.items.append(eval_case)

    def list_recent(self, limit=None):
        items = list(reversed(self.items))
        if limit is None:
            return items
        return items[:limit]


class FakePromptOverlayStore:
    def __init__(self) -> None:
        self.text = None

    def get(self):
        return self.text

    def append_candidate(self, candidate):
        self.text = f"overlay for {candidate.candidate_id}"
        return self.text


class ApplicationServiceTests(unittest.TestCase):
    def test_handle_uses_existing_session_id(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(runtime=runtime)

        result = service.handle(
            AppRequest(
                session_id="s1",
                user_id="u1",
                message="hello",
            )
        )

        self.assertEqual(result.session_id, "s1")
        self.assertEqual(runtime.calls[0]["session_id"], "s1")

    def test_handle_generates_session_id_when_missing(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(runtime=runtime)

        result = service.handle(AppRequest(user_id="u1", message="hello"))

        self.assertTrue(result.session_id)
        self.assertEqual(runtime.calls[0]["session_id"], result.session_id)

    def test_handle_uses_default_system_prompt(self) -> None:
        runtime = FakeRuntime()
        service = ApplicationService(
            runtime=runtime,
            default_system_prompt="system",
        )

        service.handle(AppRequest(user_id="u1", message="hello"))

        self.assertEqual(runtime.calls[0]["system_prompt"], "system")

    def test_get_latest_trace_delegates_to_runtime(self) -> None:
        runtime = FakeRuntime()
        runtime.latest_trace = RuntimeTrace(
            session_id="s1",
            user_id="u1",
            user_message="hello",
            final_response="done",
            status="success",
            trace_id="trace-1",
        )
        service = ApplicationService(runtime=runtime)

        trace = service.get_latest_trace(session_id="s1", user_id="u1")

        self.assertEqual(trace.trace_id, "trace-1")

    def test_get_session_traces_delegates_to_runtime(self) -> None:
        runtime = FakeRuntime()
        runtime.session_traces = [
            RuntimeTrace(
                session_id="s1",
                user_id="u1",
                user_message="hello",
                final_response="done",
                status="success",
                trace_id="trace-1",
            )
        ]
        service = ApplicationService(runtime=runtime)

        traces = service.get_session_traces("s1", user_id="u1")

        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].trace_id, "trace-1")

    def test_add_and_list_candidates_use_store(self) -> None:
        service = ApplicationService(
            runtime=FakeRuntime(),
            candidate_store=FakeCandidateStore(),
        )
        candidate = EvolutionCandidate(
            target="prompt",
            summary="Review prompt",
            rationale="Need better final answer",
        )

        service.add_candidate(candidate)

        items = service.list_candidates(limit=10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].summary, "Review prompt")

    def test_add_candidate_supersedes_older_candidate_in_same_scope(self) -> None:
        store = FakeCandidateStore()
        service = ApplicationService(
            runtime=FakeRuntime(),
            candidate_store=store,
        )
        older = EvolutionCandidate(
            target="prompt",
            summary="Old prompt candidate",
            rationale="Need better answer",
            metadata={
                "workflow_name": "prototype-baseline",
                "task_name": "runtime-trace-check",
            },
        )
        newer = EvolutionCandidate(
            target="prompt",
            summary="New prompt candidate",
            rationale="Need even better answer",
            metadata={
                "workflow_name": "prototype-baseline",
                "task_name": "runtime-trace-check",
            },
        )

        service.add_candidate(older)
        service.add_candidate(newer)

        updated_older = service.get_candidate(older.candidate_id)
        updated_newer = service.get_candidate(newer.candidate_id)
        self.assertIsNotNone(updated_older)
        self.assertIsNotNone(updated_newer)
        self.assertEqual(updated_older.status, "superseded")
        self.assertEqual(updated_older.review_note, f"superseded by {newer.candidate_id}")
        self.assertEqual(updated_newer.status, "pending")

    def test_add_candidate_does_not_supersede_different_scope(self) -> None:
        store = FakeCandidateStore()
        service = ApplicationService(
            runtime=FakeRuntime(),
            candidate_store=store,
        )
        older = EvolutionCandidate(
            target="prompt",
            summary="Old prompt candidate",
            rationale="Need better answer",
            metadata={
                "workflow_name": "prototype-baseline",
                "task_name": "runtime-trace-check",
            },
        )
        newer = EvolutionCandidate(
            target="prompt",
            summary="Different step candidate",
            rationale="Need better search",
            metadata={
                "workflow_name": "prototype-baseline",
                "task_name": "workspace-search",
            },
        )

        service.add_candidate(older)
        service.add_candidate(newer)

        updated_older = service.get_candidate(older.candidate_id)
        self.assertIsNotNone(updated_older)
        self.assertEqual(updated_older.status, "pending")

    def test_add_candidate_archives_validated_candidate_in_same_scope(self) -> None:
        store = FakeCandidateStore()
        service = ApplicationService(
            runtime=FakeRuntime(),
            candidate_store=store,
        )
        validated = EvolutionCandidate(
            target="prompt",
            summary="Validated prompt candidate",
            rationale="Worked before",
            status="verified",
            metadata={
                "workflow_name": "prototype-baseline",
                "task_name": "runtime-trace-check",
            },
        )
        newer = EvolutionCandidate(
            target="prompt",
            summary="New prompt candidate",
            rationale="Need new attempt",
            metadata={
                "workflow_name": "prototype-baseline",
                "task_name": "runtime-trace-check",
            },
        )

        service.add_candidate(validated)
        service.add_candidate(newer)

        archived = service.get_candidate(validated.candidate_id)
        current = service.get_candidate(newer.candidate_id)
        self.assertIsNotNone(archived)
        self.assertIsNotNone(current)
        self.assertEqual(archived.status, "archived")
        self.assertEqual(
            archived.review_note,
            f"archived when new candidate {newer.candidate_id} entered scope",
        )
        self.assertEqual(current.status, "pending")

    def test_validated_candidate_archives_older_validated_candidate_in_same_scope(self) -> None:
        store = FakeCandidateStore()
        service = ApplicationService(
            runtime=FakeRuntime(),
            candidate_store=store,
        )
        older = EvolutionCandidate(
            target="prompt",
            summary="Older validated prompt candidate",
            rationale="Old result",
            status="no_improvement",
            metadata={
                "workflow_name": "prototype-baseline",
                "task_name": "runtime-trace-check",
            },
        )
        newer = EvolutionCandidate(
            target="prompt",
            summary="Newer prompt candidate",
            rationale="New result",
            metadata={
                "workflow_name": "prototype-baseline",
                "task_name": "runtime-trace-check",
            },
        )

        service.add_candidate(older)
        service.add_candidate(newer)
        updated = service.update_candidate_status(newer.candidate_id, "verified", review_note="validated")

        self.assertIsNotNone(updated)
        archived = service.get_candidate(older.candidate_id)
        current = service.get_candidate(newer.candidate_id)
        self.assertIsNotNone(archived)
        self.assertIsNotNone(current)
        self.assertEqual(archived.status, "archived")
        self.assertEqual(
            archived.review_note,
            f"archived when new candidate {newer.candidate_id} entered scope",
        )
        self.assertEqual(current.status, "verified")

    def test_update_candidate_status_uses_store(self) -> None:
        store = FakeCandidateStore()
        service = ApplicationService(
            runtime=FakeRuntime(),
            candidate_store=store,
        )
        candidate = EvolutionCandidate(
            target="prompt",
            summary="Review prompt",
            rationale="Need better final answer",
        )
        service.add_candidate(candidate)

        updated = service.update_candidate_status(candidate.candidate_id, "accepted", review_note="good")

        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "accepted")
        self.assertEqual(updated.review_note, "good")

    def test_apply_prompt_candidate_uses_overlay_store(self) -> None:
        overlay_store = FakePromptOverlayStore()
        service = ApplicationService(
            runtime=FakeRuntime(),
            candidate_store=FakeCandidateStore(),
            prompt_overlay_store=overlay_store,
        )
        candidate = EvolutionCandidate(
            target="prompt",
            summary="Review prompt",
            rationale="Need better final answer",
        )
        service.add_candidate(candidate)

        updated = service.apply_candidate(candidate.candidate_id, review_note="applied")

        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "applied")
        self.assertEqual(updated.review_note, "applied")
        self.assertEqual(overlay_store.text, f"overlay for {candidate.candidate_id}")

    def test_apply_non_prompt_candidate_is_rejected(self) -> None:
        overlay_store = FakePromptOverlayStore()
        service = ApplicationService(
            runtime=FakeRuntime(),
            candidate_store=FakeCandidateStore(),
            prompt_overlay_store=overlay_store,
        )
        candidate = EvolutionCandidate(
            target="tooling",
            summary="Review tooling",
            rationale="Need better tool selection",
        )
        service.add_candidate(candidate)

        updated = service.apply_candidate(candidate.candidate_id)

        self.assertIsNone(updated)
        self.assertIsNone(overlay_store.text)

    def test_add_and_list_eval_cases_use_store(self) -> None:
        service = ApplicationService(
            runtime=FakeRuntime(),
            eval_case_store=FakeEvalCaseStore(),
        )
        eval_case = EvalCase(
            workflow_name="prototype-baseline",
            source_session_id="wf-1",
            replay_session_id="wf-2",
            source_average_score=1.0,
            replay_average_score=0.8,
            score_delta=-0.2,
            status="regressed",
            summary="Workflow replay regressed compared with the source run",
        )

        service.add_eval_case(eval_case)

        items = service.list_eval_cases(limit=10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].workflow_name, "prototype-baseline")


if __name__ == "__main__":
    unittest.main()
