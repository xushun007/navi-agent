from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from inspect_ai.model import ChatMessageAssistant
from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState, solver

from navi_agent.app import AppRequest, ApplicationService
from navi_agent.app.bootstrap import build_application
from navi_agent.runtime import DenyAllApprovalProvider, RuntimeMode


@dataclass(frozen=True, slots=True)
class NaviInspectResult:
    session_id: str
    run_id: str
    trace_id: str
    status: str
    completion: str
    iterations: int
    duration_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float

    def metadata(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "status": self.status,
            "iterations": self.iterations,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


class NaviInspectRunner:
    def __init__(self, app: ApplicationService) -> None:
        self._app = app
        self._lock = Lock()

    def run(self, prompt: str, *, suite: str, sample_id: str) -> NaviInspectResult:
        with self._lock:
            return self._run(prompt, suite=suite, sample_id=sample_id)

    def _run(self, prompt: str, *, suite: str, sample_id: str) -> NaviInspectResult:
        session_id = f"inspect:{suite}:{sample_id}:{uuid4().hex[:8]}"
        user_id = f"inspect-{suite}"
        result = self._app.handle(
            AppRequest(
                session_id=session_id,
                user_id=user_id,
                message=prompt,
                source="inspect",
                mode=RuntimeMode.EVAL,
            )
        )
        trace = self._app.get_latest_trace(
            session_id=session_id,
            user_id=user_id,
        )
        if trace is None:
            raise RuntimeError(f"Navi runtime did not record a trace for {sample_id}")
        return NaviInspectResult(
            session_id=session_id,
            run_id=result.run_id,
            trace_id=trace.trace_id,
            status=result.status,
            completion=result.final_response,
            iterations=trace.total_iterations,
            duration_ms=trace.duration_ms,
            input_tokens=sum(call.input_tokens for call in trace.model_calls),
            output_tokens=sum(call.output_tokens for call in trace.model_calls),
            cost_usd=sum(call.cost_usd or 0.0 for call in trace.model_calls),
        )


@solver
def navi_agent_solver(*, suite: str, runner: NaviInspectRunner):
    async def solve(state: TaskState, generate):
        result = await asyncio.to_thread(
            runner.run,
            state.user_prompt.text,
            suite=suite,
            sample_id=str(state.sample_id),
        )
        state.messages.append(ChatMessageAssistant(content=result.completion))
        state.output.completion = result.completion
        state.metadata["navi"] = result.metadata()
        return state

    return solve


@scorer(metrics=[accuracy()])
def navi_runtime_success():
    async def score(state: TaskState, target: Target):
        metadata = state.metadata.get("navi") or {}
        passed = metadata.get("status") == "success" and bool(state.output.completion.strip())
        return Score(
            value="C" if passed else "I",
            explanation=(
                f"status={metadata.get('status')} "
                f"trace_id={metadata.get('trace_id')} "
                f"iterations={metadata.get('iterations')}"
            ),
        )

    return score


def build_navi_inspect_runner(
    *,
    disabled_toolsets: list[str] | None = None,
) -> NaviInspectRunner:
    return NaviInspectRunner(
        app=build_application(
            approval_provider=DenyAllApprovalProvider(),
            disabled_toolsets=disabled_toolsets,
        ),
    )
